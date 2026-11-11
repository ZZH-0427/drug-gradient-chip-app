# -*- coding: utf-8 -*-
from __future__ import annotations

"""
train_physics_guided_dualtask_gnn_experiment_D.py
=================================================

Physics-GNN 对照实验 D：Balanced Sampler + 中等辅助损失权重。

实验目的
--------
本文件在实验 B 的基础上只调整辅助损失权重：

    Balanced Sampler：开启
    FlowLogMSE：0.25
    FlowLogMAE：0.025
    TotalMass：0.075
    TrackerMass：0.075
    浓度损失、网络结构、数据划分、标准化、学习率和早停规则：保持不变

因此：
1. 与实验 B（开启采样器 + 低辅助权重）比较，可判断提高辅助权重后的影响；
2. 与 V4（开启采样器 + 原辅助权重）比较，可判断中等权重是否取得更好的浓度—物理折中；
3. 与 V5（关闭采样器 + 低辅助权重）不构成严格单变量比较。

核心设置
--------
1. 每个完整芯片节点直接对应一个出口：
       node 2 -> y1 / q1
       node 3 -> y2 / q2
       ...
       node 7 -> y6 / q6

2. 相对通导能力主要决定浓度：
       左右宽度比、左右距离比 -> concentration head

3. 共同通导尺度主要决定流量：
       几何平均宽度、宽度和、几何平均距离 -> flow head

4. GNN 消息传递学习：
       安装位置、弯曲结构、六芯片之间的全局竞争与耦合修正。

5. 双任务监督：
       六个出口浓度 + 六个出口质量流量绝对值。

6. 物理约束：
       总质量守恒 + 示踪剂质量守恒。

7. 数据采样：
       默认开启 WeightedRandomSampler；不复制文件、不生成新样本，
       仅在每个 epoch 内按 data_version 和 structure_key 调整抽样概率。
       可使用 --no-balanced-sampler 临时关闭，仅用于额外核验。

重要前提
--------
必须先依次运行：
    build_standard_dataset_v5.py
    转到gnn.py
    转到physics_gnn_v4.py
    生成7算法统一划分.py

本程序会拒绝以下情况：
1. 中转数据仍有样本未进入普通 GNN；
2. 盲测样本进入训练数据集；
3. 完全重复输入跨越 train/val/test。

同目录需要：
    train_physics_gnn_shared_split.py

默认输出
--------
模型：
    GNN/Physics-GNN/model/experiment_D_balanced_medium_weight/seed_44/

报告：
    GNN/Physics-GNN/报告/experiment_D_balanced_medium_weight/seed_44/

主要检查点：
    best_concentration_checkpoint.pt
    best_joint_checkpoint.pt

兼容检查点：
    best_dualtask_checkpoint.pt
其内容与 best_concentration_checkpoint.pt 一致，便于原有反向设计代码读取。
"""

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.utils.data import WeightedRandomSampler
from torch_geometric.loader import DataLoader
from torch_geometric.nn import TransformerConv


# =============================================================================
# 0. 路径与公共框架
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
GNN_ROOT = SCRIPT_DIR.parent

if (SCRIPT_DIR / "train_physics_gnn_shared_split.py").is_file():
    PHYSICS_GNN_DIR = SCRIPT_DIR
else:
    PHYSICS_GNN_DIR = GNN_ROOT / "Physics-GNN"

for import_dir in (SCRIPT_DIR, PHYSICS_GNN_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

try:
    import train_physics_gnn_shared_split as base
except ImportError as exc:
    raise ImportError(
        "找不到 train_physics_gnn_shared_split.py。\n"
        f"已检查：{SCRIPT_DIR}\n"
        f"以及：{PHYSICS_GNN_DIR}"
    ) from exc


SCRIPT_NAME = "train_physics_guided_dualtask_gnn_experiment_D.py"
SCRIPT_VERSION = "5.2.0-expD"
EXPERIMENT_TYPE = "experiment_D_balanced_sampler_medium_auxiliary_weights"

EXPECTED_NODE_COUNT = 8
EXPECTED_NODE_FEATURE_DIM = 15
EXPECTED_EDGE_COUNT = 24
EXPECTED_EDGE_FEATURE_DIM = 9
EXPECTED_CHIP_COUNT = 6
EXPECTED_OUTPUT_DIM = 6
EXPECTED_GLOBAL_FEATURE_DIM = 2
EXPECTED_CHIP_PHYSICS_DIM = 7

CHIP_NODE_START_INDEX = 2
FLOW_EPS = 1.0e-18

CHIP_PHYSICS_FEATURE_NAMES = (
    "log_width_ratio_left_over_right",
    "normalized_width_difference",
    "geometric_mean_width",
    "width_sum",
    "log_distance_ratio_right_over_left",
    "normalized_distance_difference",
    "geometric_mean_distance",
)

# 实验D先用seed 44，与实验B进行严格单变量权重对照。
DIRECT_CLICK_SEED = 44
DIRECT_CLICK_FORCE = False

# 实验D继续默认开启均衡采样；它只改变抽样概率，不生成新样本。
# 这不是数据增强开关；本程序从始至终都不会生成新样本。
USE_BALANCED_SAMPLER = True

# True：若physics转换报告显示中转样本有未进入普通GNN的样本，立即停止。
REQUIRE_ZERO_IGNORED_STANDARD_SAMPLES = True

# True：任何盲测样本进入当前数据集都立即停止。
REQUIRE_NO_BLIND_TEST = True

# False：允许随机sample_id划分中同一structure_key跨集合。
# 真正测试外部结构泛化时，应改为True并使用按结构生成的shared_split。
REQUIRE_STRUCTURE_DISJOINT_SPLIT = False

# 实验D使用V4与实验B之间的中等辅助损失权重。
# 保留流量与物理约束，但降低辅助任务对浓度主任务的竞争。
LAMBDA_CONCENTRATION_MSE = 1.0
LAMBDA_CONCENTRATION_MAE = 0.10
LAMBDA_FLOW_MSE = 0.25
LAMBDA_FLOW_MAE = 0.025
LAMBDA_TOTAL_MASS = 0.075
LAMBDA_TRACKER_MASS = 0.075

# 联合检查点仍使用此分数；主检查点只按验证集浓度RMSE选择。
SELECTION_FLOW_LOG_RMSE_WEIGHT = 0.10

DATASET_CANDIDATES = [
    PHYSICS_GNN_DIR / "数据集" / "physics_gnn_dataset.pt",
    PHYSICS_GNN_DIR / "physics_gnn_dataset.pt",
]

SHARED_SPLIT_CANDIDATES = [
    GNN_ROOT / "shared_split.json",
    GNN_ROOT / "Gnndata" / "数据集" / "shared_split.json",
    GNN_ROOT / "Gnndata" / "shared_split.json",
    GNN_ROOT / "shared_split报告" / "shared_split.json",
    PHYSICS_GNN_DIR / "shared_split.json",
]


def first_existing(candidates: Sequence[Path], description: str) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    searched = "\n".join(f"  - {path}" for path in candidates)
    raise FileNotFoundError(
        f"没有找到{description}。\n已经检查：\n{searched}"
    )


DEFAULT_DATASET_PATH = first_existing(
    DATASET_CANDIDATES,
    "Physics-GNN V4 数据集",
)

DEFAULT_SPLIT_PATH = first_existing(
    SHARED_SPLIT_CANDIDATES,
    "shared_split.json",
)


# 与公共框架维度保持一致。
for name, value in {
    "EXPECTED_NODE_COUNT": EXPECTED_NODE_COUNT,
    "EXPECTED_NODE_FEATURE_DIM": EXPECTED_NODE_FEATURE_DIM,
    "EXPECTED_EDGE_COUNT": EXPECTED_EDGE_COUNT,
    "EXPECTED_EDGE_FEATURE_DIM": EXPECTED_EDGE_FEATURE_DIM,
    "EXPECTED_EDGE_ATTR_DIM": EXPECTED_EDGE_FEATURE_DIM,
    "EXPECTED_EDGE_DIM": EXPECTED_EDGE_FEATURE_DIM,
    "EXPECTED_OUTPUT_DIM": EXPECTED_OUTPUT_DIM,
    "EXPECTED_GLOBAL_FEATURE_DIM": EXPECTED_GLOBAL_FEATURE_DIM,
}.items():
    if hasattr(base, name):
        setattr(base, name, value)


# =============================================================================
# 1. 参数
# =============================================================================

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="训练Physics-GNN实验D：均衡采样 + 中等辅助损失权重。"
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
    )
    parser.add_argument(
        "--shared-split",
        type=Path,
        default=DEFAULT_SPLIT_PATH,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DIRECT_CLICK_SEED,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    sampler_group = parser.add_mutually_exclusive_group()
    sampler_group.add_argument(
        "--balanced-sampler",
        action="store_true",
        help=(
            "开启old/new与structure_key均衡采样；"
            "实验D默认已经开启。"
        ),
    )
    sampler_group.add_argument(
        "--no-balanced-sampler",
        action="store_true",
        help=(
            "显式关闭均衡采样；仅用于额外核验，"
            "不属于实验D的正式默认设置。"
        ),
    )
    parser.add_argument(
        "--require-structure-disjoint",
        action="store_true",
        help="要求train/val/test的structure_key完全不重叠。",
    )

    return parser


def parse_args() -> argparse.Namespace:
    parser = build_argument_parser()

    if len(sys.argv) == 1:
        direct = ["--seed", str(DIRECT_CLICK_SEED)]
        if DIRECT_CLICK_FORCE:
            direct.append("--force")
        return parser.parse_args(direct)

    return parser.parse_args()


def default_model_dir(seed: int) -> Path:
    return (
        PHYSICS_GNN_DIR
        / "model"
        / "experiment_D_balanced_medium_weight"
        / f"seed_{seed}"
    )


def default_report_dir(seed: int) -> Path:
    return (
        PHYSICS_GNN_DIR
        / "报告"
        / "experiment_D_balanced_medium_weight"
        / f"seed_{seed}"
    )


# =============================================================================
# 2. 工具与严格数据预检查
# =============================================================================

def tensor_shape(value: Any) -> Optional[Tuple[int, ...]]:
    if not torch.is_tensor(value):
        return None
    return tuple(int(size) for size in value.shape)


def graph_text(graph: Any, name: str, default: str = "") -> str:
    value = getattr(graph, name, default)
    return str(value).strip()


def graph_bool(graph: Any, name: str, default: bool = False) -> bool:
    value = getattr(graph, name, default)

    if torch.is_tensor(value):
        if value.numel() == 0:
            return default
        return bool(value.reshape(-1)[0].item())

    return bool(value)


def get_concentration_target(graph: Any) -> Tensor:
    value = getattr(graph, "concentration_target", None)

    if torch.is_tensor(value) and int(value.numel()) == EXPECTED_OUTPUT_DIM:
        return value.detach().float().reshape(EXPECTED_OUTPUT_DIM, 1)

    value = getattr(graph, "y", None)
    if torch.is_tensor(value) and int(value.numel()) == EXPECTED_OUTPUT_DIM:
        return value.detach().float().reshape(EXPECTED_OUTPUT_DIM, 1)

    raise RuntimeError("缺少六个浓度目标。")


def get_flow_target(graph: Any) -> Tensor:
    value = getattr(graph, "outlet_flow_target", None)

    if not torch.is_tensor(value) or int(value.numel()) != EXPECTED_OUTPUT_DIM:
        raise RuntimeError("缺少 outlet_flow_target[6,1]。")

    value = value.detach().float().reshape(EXPECTED_OUTPUT_DIM, 1).abs()

    if not bool(torch.isfinite(value).all().item()):
        raise RuntimeError("outlet_flow_target包含NaN/Inf。")

    if bool((value <= 0.0).any().item()):
        raise RuntimeError("outlet_flow_target必须全部为正值。")

    return value


def get_inlet_flow_abs(graph: Any) -> Tensor:
    for name in (
        "inlet_mass_flow_abs",
        "inlet_mass_flow",
        "q_in",
        "inlet_flow",
    ):
        value = getattr(graph, name, None)
        if torch.is_tensor(value) and int(value.numel()) == 2:
            value = value.detach().float().reshape(1, 2).abs()
            if bool(torch.isfinite(value).all().item()):
                return value

    raise RuntimeError("缺少两个入口质量流量。")


def validate_v4_dataset(
    payload: Mapping[str, Any],
    graphs: Sequence[Any],
) -> Dict[str, Any]:
    if not graphs:
        raise RuntimeError("physics_gnn_dataset.pt中的graphs为空。")

    physics_conversion = payload.get("physics_conversion", {})
    ignored_count = 0

    if isinstance(physics_conversion, Mapping):
        try:
            ignored_count = int(
                physics_conversion.get(
                    "ignored_extra_standard_sample_count",
                    0,
                )
            )
        except (TypeError, ValueError):
            ignored_count = 0

    if REQUIRE_ZERO_IGNORED_STANDARD_SAMPLES and ignored_count > 0:
        raise RuntimeError(
            "当前Physics-GNN数据集并未包含全部中转样本。\n"
            f"ignored_extra_standard_sample_count={ignored_count}\n\n"
            "这正对应你刚才看到的：普通GNN=3455，中转数据=3886。\n"
            "请先重新运行最新版“转到gnn.py”，使普通GNN包含全部有效样本，\n"
            "再重新运行“转到physics_gnn_v4.py”和统一划分程序。"
        )

    invalid: List[str] = []
    version_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    structure_counter: Counter[str] = Counter()
    blind_count = 0

    for index, graph in enumerate(graphs):
        sample_id = graph_text(graph, "sample_id", f"index_{index}")
        reasons: List[str] = []

        if tensor_shape(getattr(graph, "x", None)) != (
            EXPECTED_NODE_COUNT,
            EXPECTED_NODE_FEATURE_DIM,
        ):
            reasons.append(
                f"x={tensor_shape(getattr(graph, 'x', None))}，应为(8,15)"
            )

        if tensor_shape(getattr(graph, "edge_index", None)) != (
            2,
            EXPECTED_EDGE_COUNT,
        ):
            reasons.append("edge_index应为(2,24)")

        if tensor_shape(getattr(graph, "edge_attr", None)) != (
            EXPECTED_EDGE_COUNT,
            EXPECTED_EDGE_FEATURE_DIM,
        ):
            reasons.append("edge_attr应为(24,9)")

        if tensor_shape(getattr(graph, "chip_physics", None)) != (
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        ):
            reasons.append("chip_physics应为(6,7)")

        try:
            concentration = get_concentration_target(graph)
            flow = get_flow_target(graph)
            inlet_flow = get_inlet_flow_abs(graph)
        except Exception as exc:
            reasons.append(str(exc))
            concentration = None
            flow = None
            inlet_flow = None

        u = getattr(graph, "u", None)
        if not torch.is_tensor(u) or int(u.numel()) != 2:
            reasons.append("u应包含2个入口浓度")

        for field_name, value in (
            ("x", getattr(graph, "x", None)),
            ("edge_attr", getattr(graph, "edge_attr", None)),
            ("chip_physics", getattr(graph, "chip_physics", None)),
            ("concentration", concentration),
            ("flow", flow),
            ("inlet_flow", inlet_flow),
            ("u", u),
        ):
            if torch.is_tensor(value) and not bool(
                torch.isfinite(value).all().item()
            ):
                reasons.append(f"{field_name}含NaN/Inf")

        data_version = graph_text(graph, "data_version", "unknown") or "unknown"
        source_group = graph_text(graph, "source_group", "unknown") or "unknown"
        structure_key = graph_text(graph, "structure_key", "")

        if not structure_key:
            reasons.append("缺少structure_key")

        version_counter[data_version] += 1
        source_counter[source_group] += 1
        structure_counter[structure_key or "missing"] += 1

        if graph_bool(graph, "is_blind_test", False):
            blind_count += 1
            if REQUIRE_NO_BLIND_TEST:
                reasons.append("盲测样本不允许进入训练数据集")

        if reasons:
            invalid.append(f"{sample_id}：" + "；".join(reasons))
            if len(invalid) >= 20:
                break

    if invalid:
        raise RuntimeError(
            "Physics-GNN V4数据预检查失败，前20个问题：\n  - "
            + "\n  - ".join(invalid)
        )

    return {
        "graph_count": len(graphs),
        "ignored_extra_standard_sample_count": ignored_count,
        "data_version_counts": dict(sorted(version_counter.items())),
        "source_group_counts": dict(sorted(source_counter.items())),
        "unique_structure_count": len(structure_counter),
        "structure_counts": dict(sorted(structure_counter.items())),
        "blind_test_count": blind_count,
    }


def audit_split_groups(
    raw_splits: Mapping[str, Sequence[Any]],
    require_structure_disjoint: bool,
) -> Dict[str, Any]:
    split_names = ("train", "val", "test")

    structure_sets: Dict[str, set[str]] = {}
    duplicate_sets: Dict[str, set[str]] = {}
    version_counts: Dict[str, Dict[str, int]] = {}

    for split_name in split_names:
        graphs = raw_splits[split_name]

        structure_sets[split_name] = {
            graph_text(graph, "structure_key", "")
            for graph in graphs
            if graph_text(graph, "structure_key", "")
        }

        duplicate_sets[split_name] = {
            graph_text(graph, "duplicate_group_key", "")
            for graph in graphs
            if graph_text(graph, "duplicate_group_key", "")
        }

        version_counts[split_name] = dict(
            Counter(
                graph_text(graph, "data_version", "unknown") or "unknown"
                for graph in graphs
            )
        )

    structure_overlaps = {
        "train_val": sorted(
            structure_sets["train"] & structure_sets["val"]
        ),
        "train_test": sorted(
            structure_sets["train"] & structure_sets["test"]
        ),
        "val_test": sorted(
            structure_sets["val"] & structure_sets["test"]
        ),
    }

    duplicate_overlaps = {
        "train_val": sorted(
            duplicate_sets["train"] & duplicate_sets["val"]
        ),
        "train_test": sorted(
            duplicate_sets["train"] & duplicate_sets["test"]
        ),
        "val_test": sorted(
            duplicate_sets["val"] & duplicate_sets["test"]
        ),
    }

    duplicate_leak_count = sum(
        len(values)
        for values in duplicate_overlaps.values()
    )

    if duplicate_leak_count > 0:
        raise RuntimeError(
            "发现完全相同输入跨越train/val/test，存在重复样本泄漏。\n"
            f"重复组交叉数量={duplicate_leak_count}\n"
            "请重新生成统一划分。"
        )

    structure_overlap_count = sum(
        len(values)
        for values in structure_overlaps.values()
    )

    if require_structure_disjoint and structure_overlap_count > 0:
        raise RuntimeError(
            "当前要求按结构外部泛化划分，"
            "但同一structure_key仍跨越train/val/test。\n"
            f"结构交叉数量={structure_overlap_count}"
        )

    return {
        "version_counts": version_counts,
        "structure_overlap_count": structure_overlap_count,
        "structure_overlaps": structure_overlaps,
        "duplicate_overlap_count": duplicate_leak_count,
        "duplicate_overlaps": duplicate_overlaps,
        "structure_disjoint_required": require_structure_disjoint,
    }


# =============================================================================
# 3. 训练集专用标准化与数据准备
# =============================================================================

def fit_auxiliary_normalizers(
    train_graphs: Sequence[Any],
) -> Dict[str, Tensor]:
    chip_values = torch.cat(
        [
            graph.chip_physics.detach().float().reshape(
                EXPECTED_CHIP_COUNT,
                EXPECTED_CHIP_PHYSICS_DIM,
            )
            for graph in train_graphs
        ],
        dim=0,
    )

    chip_mean = chip_values.mean(dim=0)
    chip_std = chip_values.std(dim=0, unbiased=False)
    chip_std = torch.where(
        chip_std < 1.0e-12,
        torch.ones_like(chip_std),
        chip_std,
    )

    flow_values = torch.cat(
        [
            get_flow_target(graph).reshape(-1)
            for graph in train_graphs
        ],
        dim=0,
    )

    flow_log = torch.log(flow_values.clamp_min(FLOW_EPS))
    flow_log_mean = flow_log.mean().reshape(1)
    flow_log_std = flow_log.std(unbiased=False).reshape(1)

    if float(flow_log_std.item()) < 1.0e-12:
        flow_log_std = torch.ones_like(flow_log_std)

    return {
        "chip_physics_mean": chip_mean,
        "chip_physics_std": chip_std,
        "flow_log_mean": flow_log_mean,
        "flow_log_std": flow_log_std,
    }


def prepare_graphs(
    raw_graphs: Sequence[Any],
    base_normalizers: Mapping[str, Tensor],
    aux_normalizers: Mapping[str, Tensor],
) -> List[Any]:
    normalized_graphs = base.normalize_graphs(
        list(raw_graphs),
        base_normalizers,
    )

    prepared: List[Any] = []

    chip_mean = aux_normalizers["chip_physics_mean"].reshape(1, -1)
    chip_std = aux_normalizers["chip_physics_std"].reshape(1, -1)
    flow_log_mean = aux_normalizers["flow_log_mean"].reshape(1)
    flow_log_std = aux_normalizers["flow_log_std"].reshape(1)

    for raw_graph, graph in zip(raw_graphs, normalized_graphs):
        raw_chip = raw_graph.chip_physics.detach().float().reshape(
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        )

        flow_target = get_flow_target(raw_graph)
        concentration_target = get_concentration_target(raw_graph)
        inlet_flow_abs = get_inlet_flow_abs(raw_graph)

        graph.chip_physics = raw_chip.clone()
        graph.chip_physics_z = (
            raw_chip - chip_mean
        ) / chip_std

        graph.concentration_target = concentration_target.clone()
        graph.y = concentration_target.clone()

        graph.outlet_flow_target = flow_target.clone()
        graph.outlet_flow_log_z = (
            torch.log(flow_target.clamp_min(FLOW_EPS))
            - flow_log_mean
        ) / flow_log_std

        graph.inlet_mass_flow_abs = inlet_flow_abs.clone()
        graph.u_raw = raw_graph.u.detach().float().reshape(1, 2).clone()

        prepared.append(graph)

    return prepared


def make_balanced_sampler(
    train_graphs: Sequence[Any],
    seed: int,
) -> Tuple[WeightedRandomSampler, pd.DataFrame]:
    """
    采样概率：
        先让old/new等data_version总权重相等；
        再让同一data_version内部的每个structure_key总权重相等；
        最后让同一结构内每条DP平均分配。
    """

    version_to_structures: Dict[str, set[str]] = defaultdict(set)
    group_counts: Counter[Tuple[str, str]] = Counter()

    rows: List[Dict[str, Any]] = []

    for graph in train_graphs:
        version = graph_text(graph, "data_version", "unknown") or "unknown"
        structure = graph_text(graph, "structure_key", "missing") or "missing"

        version_to_structures[version].add(structure)
        group_counts[(version, structure)] += 1

    version_count = max(len(version_to_structures), 1)
    weights: List[float] = []

    for graph in train_graphs:
        version = graph_text(graph, "data_version", "unknown") or "unknown"
        structure = graph_text(graph, "structure_key", "missing") or "missing"

        structure_count_in_version = max(
            len(version_to_structures[version]),
            1,
        )
        samples_in_group = max(
            group_counts[(version, structure)],
            1,
        )

        weight = 1.0 / (
            version_count
            * structure_count_in_version
            * samples_in_group
        )
        weights.append(weight)

    weight_tensor = torch.tensor(weights, dtype=torch.double)
    generator = torch.Generator()
    generator.manual_seed(seed)

    sampler = WeightedRandomSampler(
        weights=weight_tensor,
        num_samples=len(train_graphs),
        replacement=True,
        generator=generator,
    )

    for (version, structure), count in sorted(group_counts.items()):
        single_weight = 1.0 / (
            version_count
            * max(len(version_to_structures[version]), 1)
            * count
        )

        rows.append({
            "data_version": version,
            "structure_key": structure,
            "sample_count": count,
            "single_sample_weight": single_weight,
            "group_total_weight": single_weight * count,
        })

    return sampler, pd.DataFrame(rows)


# =============================================================================
# 4. 双任务模型
# =============================================================================

class PhysicsGuidedDualTaskGNN(nn.Module):
    def __init__(
        self,
        *,
        in_channels: int,
        edge_dim: int,
        global_feature_dim: int,
        hidden_channels: int,
        heads: int,
        num_layers: int,
        dropout: float,
        use_edge_attr: bool,
        x_mean: Tensor,
        x_std: Tensor,
        u_mean: Tensor,
        u_std: Tensor,
        flow_log_mean: Tensor,
        flow_log_std: Tensor,
    ) -> None:
        super().__init__()

        if num_layers < 1:
            raise ValueError("num_layers必须至少为1。")

        self.in_channels = int(in_channels)
        self.edge_dim = int(edge_dim)
        self.global_feature_dim = int(global_feature_dim)
        self.hidden_channels = int(hidden_channels)
        self.heads = int(heads)
        self.num_layers = int(num_layers)
        self.dropout_rate = float(dropout)
        self.use_edge_attr = bool(use_edge_attr)

        self.register_buffer(
            "x_mean",
            x_mean.detach().float().reshape(1, -1),
        )
        self.register_buffer(
            "x_std",
            x_std.detach().float().reshape(1, -1),
        )
        self.register_buffer(
            "u_mean",
            u_mean.detach().float().reshape(1, -1),
        )
        self.register_buffer(
            "u_std",
            u_std.detach().float().reshape(1, -1),
        )
        self.register_buffer(
            "flow_log_mean",
            flow_log_mean.detach().float().reshape(1),
        )
        self.register_buffer(
            "flow_log_std",
            flow_log_std.detach().float().reshape(1),
        )

        self.input_projection = nn.Linear(
            in_channels + EXPECTED_CHIP_PHYSICS_DIM,
            hidden_channels,
        )

        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()

        for _ in range(num_layers):
            kwargs: Dict[str, Any] = {
                "in_channels": hidden_channels,
                "out_channels": hidden_channels,
                "heads": heads,
                "concat": False,
                "beta": True,
                "dropout": dropout,
                "root_weight": True,
            }

            if self.use_edge_attr:
                kwargs["edge_dim"] = edge_dim

            self.convs.append(TransformerConv(**kwargs))
            self.norms.append(nn.LayerNorm(hidden_channels))

        self.dropout = nn.Dropout(dropout)

        # 浓度局部主项：两个权重保持正值。
        self.raw_width_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.raw_distance_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.local_concentration_bias = nn.Parameter(torch.zeros(1))
        self.concentration_global_gate = nn.Parameter(torch.tensor(-2.0))

        context_dim = (
            hidden_channels
            + hidden_channels
            + EXPECTED_CHIP_PHYSICS_DIM
            + global_feature_dim
        )

        self.concentration_correction_head = nn.Sequential(
            nn.Linear(context_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.GELU(),
            nn.Linear(hidden_channels // 2, 1),
        )

        # 流量头直接学习共同尺度与全局竞争后的log(flow)标准分数。
        self.flow_head = nn.Sequential(
            nn.Linear(context_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.GELU(),
            nn.Linear(hidden_channels // 2, 1),
        )

    def recover_raw_u(self, normalized_u: Tensor) -> Tensor:
        return normalized_u * self.u_std + self.u_mean

    def decode_flow(self, flow_log_z: Tensor) -> Tensor:
        flow_log = (
            flow_log_z * self.flow_log_std
            + self.flow_log_mean
        )
        return torch.exp(flow_log).clamp_min(FLOW_EPS)

    def forward(self, data: Any) -> Dict[str, Tensor]:
        graph_count = int(data.num_graphs)

        if int(data.x.shape[0]) != graph_count * EXPECTED_NODE_COUNT:
            raise RuntimeError(
                "每张图必须固定8个节点。"
            )

        node_x = data.x.reshape(
            graph_count,
            EXPECTED_NODE_COUNT,
            self.in_channels,
        )

        chip_physics_z = data.chip_physics_z.reshape(
            graph_count,
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        )

        chip_physics_raw = data.chip_physics.reshape(
            graph_count,
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        )

        physics_for_nodes = torch.zeros(
            (
                graph_count,
                EXPECTED_NODE_COUNT,
                EXPECTED_CHIP_PHYSICS_DIM,
            ),
            dtype=node_x.dtype,
            device=node_x.device,
        )

        physics_for_nodes[
            :,
            CHIP_NODE_START_INDEX:,
            :,
        ] = chip_physics_z

        node_input = torch.cat(
            [node_x, physics_for_nodes],
            dim=2,
        ).reshape(
            graph_count * EXPECTED_NODE_COUNT,
            -1,
        )

        hidden = F.gelu(
            self.input_projection(node_input)
        )

        for conv, norm in zip(self.convs, self.norms):
            residual = hidden

            if self.use_edge_attr:
                message = conv(
                    hidden,
                    data.edge_index,
                    data.edge_attr,
                )
            else:
                message = conv(
                    hidden,
                    data.edge_index,
                )

            message = self.dropout(
                F.gelu(norm(message))
            )
            hidden = residual + message

        node_hidden = hidden.reshape(
            graph_count,
            EXPECTED_NODE_COUNT,
            self.hidden_channels,
        )

        chip_hidden = node_hidden[
            :,
            CHIP_NODE_START_INDEX:,
            :,
        ]

        graph_context = node_hidden.mean(
            dim=1,
            keepdim=True,
        ).expand(
            -1,
            EXPECTED_CHIP_COUNT,
            -1,
        )

        normalized_u = data.u.reshape(graph_count, -1)
        raw_u = self.recover_raw_u(normalized_u)

        u_context = raw_u.unsqueeze(1).expand(
            -1,
            EXPECTED_CHIP_COUNT,
            -1,
        )

        context = torch.cat(
            [
                chip_hidden,
                graph_context,
                chip_physics_z,
                u_context,
            ],
            dim=2,
        )

        width_weight = F.softplus(
            self.raw_width_ratio_weight
        )
        distance_weight = F.softplus(
            self.raw_distance_ratio_weight
        )

        # 使用原始log比例，保持物理解释。
        local_logit = (
            self.local_concentration_bias
            + width_weight * chip_physics_raw[:, :, 0]
            + distance_weight * chip_physics_raw[:, :, 4]
        )

        correction = (
            self.concentration_correction_head(context)
            .squeeze(-1)
        )

        gate = torch.sigmoid(
            self.concentration_global_gate
        )

        alpha = torch.sigmoid(
            local_logit + gate * correction
        )

        inlet1 = raw_u[:, 0:1]
        inlet2 = raw_u[:, 1:2]

        concentration = (
            inlet2
            + alpha * (inlet1 - inlet2)
        )

        flow_log_z = self.flow_head(context).squeeze(-1)
        flow = self.decode_flow(flow_log_z)

        return {
            "concentration": concentration,
            "flow_log_z": flow_log_z,
            "flow": flow,
            "mixing_fraction": alpha,
            "raw_u": raw_u,
        }


# =============================================================================
# 5. 双任务损失
# =============================================================================

class DualTaskPhysicsLoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()

    def forward(
        self,
        output: Mapping[str, Tensor],
        batch: Any,
    ) -> Dict[str, Tensor]:
        graph_count = int(batch.num_graphs)

        concentration_pred = output["concentration"]
        flow_log_z_pred = output["flow_log_z"]
        flow_pred = output["flow"]
        raw_u = output["raw_u"]

        concentration_true = batch.concentration_target.reshape(
            graph_count,
            EXPECTED_OUTPUT_DIM,
        )

        flow_true = batch.outlet_flow_target.reshape(
            graph_count,
            EXPECTED_OUTPUT_DIM,
        )

        flow_log_z_true = batch.outlet_flow_log_z.reshape(
            graph_count,
            EXPECTED_OUTPUT_DIM,
        )

        inlet_flow_abs = batch.inlet_mass_flow_abs.reshape(
            graph_count,
            2,
        )

        concentration_mse = F.mse_loss(
            concentration_pred,
            concentration_true,
        )
        concentration_mae = F.l1_loss(
            concentration_pred,
            concentration_true,
        )

        flow_mse = F.mse_loss(
            flow_log_z_pred,
            flow_log_z_true,
        )
        flow_mae = F.l1_loss(
            flow_log_z_pred,
            flow_log_z_true,
        )

        inlet_total = inlet_flow_abs.sum(dim=1).clamp_min(FLOW_EPS)
        outlet_total_pred = flow_pred.sum(dim=1)

        relative_total_mass_error = (
            outlet_total_pred - inlet_total
        ) / inlet_total

        total_mass_loss = F.smooth_l1_loss(
            relative_total_mass_error,
            torch.zeros_like(relative_total_mass_error),
        )

        tracer_in = (
            inlet_flow_abs * raw_u
        ).sum(dim=1)

        tracer_out_pred = (
            flow_pred * concentration_pred
        ).sum(dim=1)

        tracker_denominator = torch.maximum(
            tracer_in.abs(),
            inlet_total * 1.0e-6,
        ).clamp_min(FLOW_EPS)

        relative_tracker_error = (
            tracer_out_pred - tracer_in
        ) / tracker_denominator

        tracker_mass_loss = F.smooth_l1_loss(
            relative_tracker_error,
            torch.zeros_like(relative_tracker_error),
        )

        total = (
            LAMBDA_CONCENTRATION_MSE * concentration_mse
            + LAMBDA_CONCENTRATION_MAE * concentration_mae
            + LAMBDA_FLOW_MSE * flow_mse
            + LAMBDA_FLOW_MAE * flow_mae
            + LAMBDA_TOTAL_MASS * total_mass_loss
            + LAMBDA_TRACKER_MASS * tracker_mass_loss
        )

        return {
            "total_loss": total,
            "concentration_mse": concentration_mse,
            "concentration_mae": concentration_mae,
            "flow_log_mse": flow_mse,
            "flow_log_mae": flow_mae,
            "total_mass_loss": total_mass_loss,
            "tracker_mass_loss": tracker_mass_loss,
            "mean_abs_relative_total_mass_error": (
                relative_total_mass_error.abs().mean()
            ),
            "mean_abs_relative_tracker_error": (
                relative_tracker_error.abs().mean()
            ),
            "flow_true": flow_true,
        }


# =============================================================================
# 6. 训练与评价
# =============================================================================

def scalar(value: Tensor) -> float:
    return float(value.detach().cpu().item())


def r2_score_numpy(true: np.ndarray, pred: np.ndarray) -> float:
    true_flat = true.reshape(-1)
    pred_flat = pred.reshape(-1)

    denominator = float(
        np.sum((true_flat - true_flat.mean()) ** 2)
    )

    if denominator <= 1.0e-20:
        return float("nan")

    numerator = float(
        np.sum((true_flat - pred_flat) ** 2)
    )

    return 1.0 - numerator / denominator


def regression_metrics(
    true: np.ndarray,
    pred: np.ndarray,
) -> Dict[str, float]:
    error = pred - true
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "r2": float(r2_score_numpy(true, pred)),
        "max_abs_error": float(np.max(np.abs(error))),
    }


def train_one_epoch_dual(
    *,
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: DualTaskPhysicsLoss,
    device: torch.device,
) -> Dict[str, float]:
    model.train()

    sums: Counter[str] = Counter()
    graph_total = 0

    for batch in loader:
        batch = batch.to(device)
        optimizer.zero_grad(set_to_none=True)

        output = model(batch)
        losses = criterion(output, batch)

        losses["total_loss"].backward()
        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            max_norm=5.0,
        )
        optimizer.step()

        count = int(batch.num_graphs)
        graph_total += count

        for name, value in losses.items():
            if torch.is_tensor(value) and value.numel() == 1:
                sums[name] += scalar(value) * count

    if graph_total == 0:
        raise RuntimeError("训练DataLoader为空。")

    return {
        name: value / graph_total
        for name, value in sums.items()
    }


@torch.no_grad()
def evaluate_dual(
    *,
    model: nn.Module,
    loader: DataLoader,
    criterion: DualTaskPhysicsLoss,
    device: torch.device,
) -> Dict[str, Any]:
    model.eval()

    loss_sums: Counter[str] = Counter()
    graph_total = 0

    concentration_true_parts: List[np.ndarray] = []
    concentration_pred_parts: List[np.ndarray] = []
    flow_true_parts: List[np.ndarray] = []
    flow_pred_parts: List[np.ndarray] = []
    flow_log_z_true_parts: List[np.ndarray] = []
    flow_log_z_pred_parts: List[np.ndarray] = []

    sample_ids: List[str] = []
    data_versions: List[str] = []
    source_groups: List[str] = []
    structure_keys: List[str] = []
    dp_names: List[str] = []
    families: List[str] = []

    for batch in loader:
        batch = batch.to(device)
        output = model(batch)
        losses = criterion(output, batch)

        count = int(batch.num_graphs)
        graph_total += count

        for name, value in losses.items():
            if torch.is_tensor(value) and value.numel() == 1:
                loss_sums[name] += scalar(value) * count

        concentration_true = batch.concentration_target.reshape(
            count,
            EXPECTED_OUTPUT_DIM,
        )
        flow_true = batch.outlet_flow_target.reshape(
            count,
            EXPECTED_OUTPUT_DIM,
        )
        flow_log_z_true = batch.outlet_flow_log_z.reshape(
            count,
            EXPECTED_OUTPUT_DIM,
        )

        concentration_true_parts.append(
            concentration_true.detach().cpu().numpy()
        )
        concentration_pred_parts.append(
            output["concentration"].detach().cpu().numpy()
        )
        flow_true_parts.append(
            flow_true.detach().cpu().numpy()
        )
        flow_pred_parts.append(
            output["flow"].detach().cpu().numpy()
        )
        flow_log_z_true_parts.append(
            flow_log_z_true.detach().cpu().numpy()
        )
        flow_log_z_pred_parts.append(
            output["flow_log_z"].detach().cpu().numpy()
        )

        def extend_attr(target: List[str], attr_name: str) -> None:
            value = getattr(batch, attr_name, None)

            if isinstance(value, (list, tuple)):
                target.extend(str(item) for item in value)
            elif value is None:
                target.extend([""] * count)
            else:
                target.extend([str(value)] * count)

        extend_attr(sample_ids, "sample_id")
        extend_attr(data_versions, "data_version")
        extend_attr(source_groups, "source_group")
        extend_attr(structure_keys, "structure_key")
        extend_attr(dp_names, "dp_name")
        extend_attr(families, "family")

    if graph_total == 0:
        raise RuntimeError("评价DataLoader为空。")

    concentration_true = np.concatenate(concentration_true_parts, axis=0)
    concentration_pred = np.concatenate(concentration_pred_parts, axis=0)
    flow_true = np.concatenate(flow_true_parts, axis=0)
    flow_pred = np.concatenate(flow_pred_parts, axis=0)
    flow_log_z_true = np.concatenate(flow_log_z_true_parts, axis=0)
    flow_log_z_pred = np.concatenate(flow_log_z_pred_parts, axis=0)

    concentration_metrics = regression_metrics(
        concentration_true,
        concentration_pred,
    )
    flow_metrics = regression_metrics(
        flow_true,
        flow_pred,
    )
    flow_log_metrics = regression_metrics(
        flow_log_z_true,
        flow_log_z_pred,
    )

    concentration_per_outlet: Dict[str, float] = {}
    flow_per_outlet: Dict[str, float] = {}

    for outlet_index in range(EXPECTED_OUTPUT_DIM):
        number = outlet_index + 1

        conc_metrics = regression_metrics(
            concentration_true[:, outlet_index],
            concentration_pred[:, outlet_index],
        )
        flow_outlet_metrics = regression_metrics(
            flow_true[:, outlet_index],
            flow_pred[:, outlet_index],
        )

        for name, value in conc_metrics.items():
            concentration_per_outlet[
                f"y{number}_{name}"
            ] = value

        for name, value in flow_outlet_metrics.items():
            flow_per_outlet[
                f"q{number}_{name}"
            ] = value

    physics_losses = {
        name: value / graph_total
        for name, value in loss_sums.items()
    }

    return {
        "graph_count": graph_total,
        "concentration_true": concentration_true,
        "concentration_pred": concentration_pred,
        "flow_true": flow_true,
        "flow_pred": flow_pred,
        "flow_log_z_true": flow_log_z_true,
        "flow_log_z_pred": flow_log_z_pred,
        "concentration_metrics": concentration_metrics,
        "flow_metrics": flow_metrics,
        "flow_log_metrics": flow_log_metrics,
        "concentration_per_outlet": concentration_per_outlet,
        "flow_per_outlet": flow_per_outlet,
        "physics_losses": physics_losses,
        "sample_ids": sample_ids,
        "data_versions": data_versions,
        "source_groups": source_groups,
        "structure_keys": structure_keys,
        "dp_names": dp_names,
        "families": families,
    }


def save_predictions(
    result: Mapping[str, Any],
    path: Path,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    concentration_true = result["concentration_true"]
    concentration_pred = result["concentration_pred"]
    flow_true = result["flow_true"]
    flow_pred = result["flow_pred"]

    for index in range(concentration_true.shape[0]):
        conc_error = concentration_pred[index] - concentration_true[index]
        flow_error = flow_pred[index] - flow_true[index]

        row: Dict[str, Any] = {
            "sample_id": result["sample_ids"][index],
            "dp_name": result["dp_names"][index],
            "family": result["families"][index],
            "data_version": result["data_versions"][index],
            "source_group": result["source_groups"][index],
            "structure_key": result["structure_keys"][index],
            "sample_concentration_mae": float(
                np.mean(np.abs(conc_error))
            ),
            "sample_concentration_max_abs_error": float(
                np.max(np.abs(conc_error))
            ),
            "sample_flow_mae": float(
                np.mean(np.abs(flow_error))
            ),
            "sample_flow_max_abs_error": float(
                np.max(np.abs(flow_error))
            ),
        }

        for outlet_index in range(EXPECTED_OUTPUT_DIM):
            number = outlet_index + 1

            row[f"y{number}_true"] = float(
                concentration_true[index, outlet_index]
            )
            row[f"y{number}_pred"] = float(
                concentration_pred[index, outlet_index]
            )
            row[f"y{number}_abs_error"] = float(
                abs(conc_error[outlet_index])
            )

            row[f"q{number}_true"] = float(
                flow_true[index, outlet_index]
            )
            row[f"q{number}_pred"] = float(
                flow_pred[index, outlet_index]
            )
            row[f"q{number}_abs_error"] = float(
                abs(flow_error[outlet_index])
            )

        rows.append(row)

    dataframe = pd.DataFrame(rows)
    dataframe.to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )
    return dataframe


def save_training_curve(
    train_log: pd.DataFrame,
    path: Path,
) -> None:
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(10, 6))
    axis = figure.add_subplot(111)

    axis.plot(
        train_log["epoch"],
        train_log["train_total_loss"],
        label="Train total loss",
    )
    axis.plot(
        train_log["epoch"],
        train_log["val_selection_score"],
        label="Validation concentration RMSE (selection)",
    )
    axis.plot(
        train_log["epoch"],
        train_log["val_concentration_rmse"],
        label="Validation concentration RMSE",
    )
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Value")
    axis.set_title("Physics-GNN Experiment D: Balanced Sampler + Medium Auxiliary Weights")
    axis.legend()
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(path, dpi=200)
    plt.close(figure)


# =============================================================================
# 7. 输出辅助
# =============================================================================

def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            dict(payload),
            handle,
            ensure_ascii=False,
            indent=2,
            allow_nan=True,
            default=str,
        )


def required_files() -> Tuple[str, ...]:
    return (
        "best_dualtask_model.pt",
        "best_dualtask_checkpoint.pt",
        "best_concentration_model.pt",
        "best_concentration_checkpoint.pt",
        "best_joint_model.pt",
        "best_joint_checkpoint.pt",
        "dualtask_metrics.json",
        "dualtask_prediction_results.csv",
        "joint_metrics.json",
        "joint_prediction_results.csv",
        "checkpoint_comparison.csv",
        "dualtask_train_log.csv",
        "run_config.json",
    )


def existing_result_matches(
    *,
    model_dir: Path,
    report_dir: Path,
    dataset_hash: str,
    split_hash: str,
    seed: int,
) -> bool:
    for filename in required_files():
        if (
            not (model_dir / filename).exists()
            and not (report_dir / filename).exists()
        ):
            return False

    config_path = report_dir / "run_config.json"
    if not config_path.is_file():
        return False

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        return False

    return (
        config.get("dataset_sha256") == dataset_hash
        and config.get("shared_split_sha256") == split_hash
        and int(config.get("seed", -1)) == int(seed)
        and config.get("script_version") == SCRIPT_VERSION
    )


# =============================================================================
# 8. 主程序
# =============================================================================

def main() -> None:
    args = parse_args()

    dataset_path = args.dataset.expanduser().resolve()
    split_path = args.shared_split.expanduser().resolve()

    model_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else default_model_dir(args.seed).resolve()
    )
    report_dir = (
        args.report_dir.expanduser().resolve()
        if args.report_dir is not None
        else default_report_dir(args.seed).resolve()
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        # 主输出：浓度最优检查点；兼容旧的反向设计搜索文件名。
        "best_model": model_dir / "best_dualtask_model.pt",
        "best_checkpoint": model_dir / "best_dualtask_checkpoint.pt",
        "best_concentration_model": (
            model_dir / "best_concentration_model.pt"
        ),
        "best_concentration_checkpoint": (
            model_dir / "best_concentration_checkpoint.pt"
        ),
        # 对照输出：浓度+流量联合验证分数最优检查点。
        "best_joint_model": model_dir / "best_joint_model.pt",
        "best_joint_checkpoint": (
            model_dir / "best_joint_checkpoint.pt"
        ),
        # 主测试结果对应浓度最优检查点。
        "metrics_csv": report_dir / "dualtask_metrics.csv",
        "metrics_json": report_dir / "dualtask_metrics.json",
        "predictions": report_dir / "dualtask_prediction_results.csv",
        "bad_samples": report_dir / "dualtask_bad_samples.csv",
        # 联合检查点独立测试结果。
        "joint_metrics_csv": report_dir / "joint_metrics.csv",
        "joint_metrics_json": report_dir / "joint_metrics.json",
        "joint_predictions": (
            report_dir / "joint_prediction_results.csv"
        ),
        "joint_bad_samples": report_dir / "joint_bad_samples.csv",
        "checkpoint_comparison": (
            report_dir / "checkpoint_comparison.csv"
        ),
        "train_log": report_dir / "dualtask_train_log.csv",
        "training_curve": report_dir / "dualtask_training_curve.png",
        "split_audit": report_dir / "shared_split_audit.csv",
        "group_audit": report_dir / "group_split_audit.json",
        "sampler_audit": report_dir / "balanced_sampler_audit.csv",
        "preflight": report_dir / "dataset_preflight.json",
        "run_config": report_dir / "run_config.json",
        "report": report_dir / "dualtask_experiment_report.md",
    }

    if not dataset_path.is_file():
        raise FileNotFoundError(dataset_path)

    if not split_path.is_file():
        raise FileNotFoundError(split_path)

    dataset_hash = base.sha256_file(dataset_path)
    split_hash = base.sha256_file(split_path)

    if (
        not args.force
        and existing_result_matches(
            model_dir=model_dir,
            report_dir=report_dir,
            dataset_hash=dataset_hash,
            split_hash=split_hash,
            seed=args.seed,
        )
    ):
        print("[跳过] 当前数据、划分、种子和脚本版本已有完整结果。")
        return

    start_total = time.perf_counter()

    base.set_seed(args.seed)

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    payload, original_graphs = base.load_graph_payload(dataset_path)
    preflight = validate_v4_dataset(payload, original_graphs)
    write_json(paths["preflight"], preflight)

    print()
    print("=" * 90)
    print("Physics-GNN Experiment D | Balanced Sampler + 中等辅助损失权重")
    print("=" * 90)
    print("Dataset：", dataset_path)
    print("Graph Count：", len(original_graphs))
    print("Data Version Counts：", preflight["data_version_counts"])
    print("Source Group Counts：", preflight["source_group_counts"])
    print("Unique Structures：", preflight["unique_structure_count"])
    print("Seed：", args.seed)
    print("Device：", device)
    requested_balanced_sampler = bool(args.balanced_sampler)
    use_balanced_sampler = (
        requested_balanced_sampler
        if args.balanced_sampler or args.no_balanced_sampler
        else USE_BALANCED_SAMPLER
    )
    if args.no_balanced_sampler:
        use_balanced_sampler = False

    print("Balanced Sampler：", use_balanced_sampler)
    print("Data Augmentation：False")
    print("Primary Checkpoint：Validation concentration RMSE")
    print("=" * 90)

    clean_graphs, bad_records, dataset_info = (
        base.validate_and_clean_graphs(original_graphs)
    )

    if not clean_graphs:
        raise RuntimeError(
            "公共框架清理后没有有效图。"
        )

    split_payload = base.load_json(split_path)

    raw_splits, split_audit, split_validation = (
        base.build_shared_split(
            clean_graphs,
            split_payload,
            dataset_path=dataset_path,
        )
    )

    split_audit.to_csv(
        paths["split_audit"],
        index=False,
        encoding="utf-8-sig",
    )

    require_structure_disjoint = (
        REQUIRE_STRUCTURE_DISJOINT_SPLIT
        or args.require_structure_disjoint
    )

    group_audit = audit_split_groups(
        raw_splits,
        require_structure_disjoint=require_structure_disjoint,
    )
    write_json(paths["group_audit"], group_audit)

    train_raw = list(raw_splits["train"])
    val_raw = list(raw_splits["val"])
    test_raw = list(raw_splits["test"])

    base_normalizers = dict(
        base.fit_train_normalizers(train_raw)
    )
    aux_normalizers = fit_auxiliary_normalizers(train_raw)

    normalizers: Dict[str, Tensor] = {
        **base_normalizers,
        **aux_normalizers,
    }

    train_graphs = prepare_graphs(
        train_raw,
        base_normalizers,
        aux_normalizers,
    )
    val_graphs = prepare_graphs(
        val_raw,
        base_normalizers,
        aux_normalizers,
    )
    test_graphs = prepare_graphs(
        test_raw,
        base_normalizers,
        aux_normalizers,
    )

    # use_balanced_sampler已在启动信息阶段解析完成。
    # 默认False；只有显式传入--balanced-sampler时才开启。

    if use_balanced_sampler:
        sampler, sampler_audit = make_balanced_sampler(
            train_graphs,
            seed=args.seed,
        )
        sampler_audit.to_csv(
            paths["sampler_audit"],
            index=False,
            encoding="utf-8-sig",
        )

        train_loader = DataLoader(
            train_graphs,
            batch_size=min(base.BATCH_SIZE, len(train_graphs)),
            sampler=sampler,
            shuffle=False,
            num_workers=base.NUM_WORKERS,
        )
    else:
        pd.DataFrame().to_csv(
            paths["sampler_audit"],
            index=False,
            encoding="utf-8-sig",
        )

        generator = torch.Generator()
        generator.manual_seed(args.seed)

        train_loader = DataLoader(
            train_graphs,
            batch_size=min(base.BATCH_SIZE, len(train_graphs)),
            shuffle=True,
            generator=generator,
            num_workers=base.NUM_WORKERS,
        )

    val_loader = DataLoader(
        val_graphs,
        batch_size=min(base.BATCH_SIZE, len(val_graphs)),
        shuffle=False,
        num_workers=base.NUM_WORKERS,
    )
    test_loader = DataLoader(
        test_graphs,
        batch_size=min(base.BATCH_SIZE, len(test_graphs)),
        shuffle=False,
        num_workers=base.NUM_WORKERS,
    )

    in_channels = int(train_graphs[0].x.shape[1])
    edge_dim = int(train_graphs[0].edge_attr.shape[1])
    global_feature_dim = int(train_graphs[0].u.numel())

    model = PhysicsGuidedDualTaskGNN(
        in_channels=in_channels,
        edge_dim=edge_dim,
        global_feature_dim=global_feature_dim,
        hidden_channels=base.HIDDEN_CHANNELS,
        heads=base.TRANSFORMER_HEADS,
        num_layers=base.TRANSFORMER_LAYERS,
        dropout=base.DROPOUT,
        use_edge_attr=True,
        x_mean=normalizers["x_mean"],
        x_std=normalizers["x_std"],
        u_mean=normalizers["u_mean"],
        u_std=normalizers["u_std"],
        flow_log_mean=normalizers["flow_log_mean"],
        flow_log_std=normalizers["flow_log_std"],
    ).to(device)

    criterion = DualTaskPhysicsLoss()

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=base.LEARNING_RATE,
        weight_decay=base.WEIGHT_DECAY,
    )

    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=base.LR_REDUCE_FACTOR,
        patience=base.LR_REDUCE_PATIENCE,
        min_lr=base.MIN_LEARNING_RATE,
    )

    parameter_count = base.count_trainable_parameters(model)

    print(model)
    print("Parameters：", f"{parameter_count:,}")
    print(
        "Loss："
        f"{LAMBDA_CONCENTRATION_MSE:g}*ConcentrationMSE + "
        f"{LAMBDA_CONCENTRATION_MAE:g}*ConcentrationMAE + "
        f"{LAMBDA_FLOW_MSE:g}*FlowLogMSE + "
        f"{LAMBDA_FLOW_MAE:g}*FlowLogMAE + "
        f"{LAMBDA_TOTAL_MASS:g}*TotalMass + "
        f"{LAMBDA_TRACKER_MASS:g}*TrackerMass"
    )
    print("Scaler Rule：TRAIN ONLY")

    def make_checkpoint(
        *,
        checkpoint_type: str,
        epoch_value: int,
        selection_value: float,
        val_concentration_rmse_value: float,
        val_flow_log_rmse_value: float,
    ) -> Dict[str, Any]:
        return {
            "script": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "experiment_type": EXPERIMENT_TYPE,
            "checkpoint_type": checkpoint_type,
            "primary_task": "concentration",
            "model_state_dict": model.state_dict(),
            "normalizers": {
                name: value.detach().cpu()
                for name, value in normalizers.items()
            },
            "best_epoch": int(epoch_value),
            "best_selection_score": float(selection_value),
            "best_val_concentration_rmse": float(
                val_concentration_rmse_value
            ),
            "best_val_flow_log_rmse": float(
                val_flow_log_rmse_value
            ),
            "seed": args.seed,
            "dataset_sha256": dataset_hash,
            "shared_split_sha256": split_hash,
            "architecture": {
                "model_type": "PhysicsGuidedDualTaskGNN",
                "in_channels": in_channels,
                "edge_dim": edge_dim,
                "global_feature_dim": global_feature_dim,
                "hidden_channels": base.HIDDEN_CHANNELS,
                "heads": base.TRANSFORMER_HEADS,
                "layers": base.TRANSFORMER_LAYERS,
                "dropout": base.DROPOUT,
                "chip_physics_feature_dim": (
                    EXPECTED_CHIP_PHYSICS_DIM
                ),
                "chip_physics_feature_names": list(
                    CHIP_PHYSICS_FEATURE_NAMES
                ),
                "outputs": {
                    "concentration": [6],
                    "flow_log_z": [6],
                    "flow": [6],
                },
                "concentration_bounded_by_inlets": True,
                "flow_positive_by_exponential_decoder": True,
            },
            "loss_weights": {
                "lambda_concentration_mse": (
                    LAMBDA_CONCENTRATION_MSE
                ),
                "lambda_concentration_mae": (
                    LAMBDA_CONCENTRATION_MAE
                ),
                "lambda_flow_mse": LAMBDA_FLOW_MSE,
                "lambda_flow_mae": LAMBDA_FLOW_MAE,
                "lambda_total_mass": LAMBDA_TOTAL_MASS,
                "lambda_tracker_mass": LAMBDA_TRACKER_MASS,
            },
            "balanced_sampler": use_balanced_sampler,
            "data_augmentation": False,
            "scheduler_metric": "val_concentration_rmse",
            "early_stopping_metric": "val_concentration_rmse",
            "split_validation": split_validation,
            "group_audit": group_audit,
            "dataset_info": dataset_info,
            "preflight": preflight,
        }

    best_concentration_rmse = float("inf")
    best_concentration_epoch = 0
    best_joint_score = float("inf")
    best_joint_epoch = 0
    patience_counter = 0
    train_logs: List[Dict[str, Any]] = []

    training_start = time.perf_counter()

    for epoch in range(1, base.MAX_EPOCHS + 1):
        train_result = train_one_epoch_dual(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            criterion=criterion,
            device=device,
        )

        val_result = evaluate_dual(
            model=model,
            loader=val_loader,
            criterion=criterion,
            device=device,
        )

        val_concentration_rmse = float(
            val_result["concentration_metrics"]["rmse"]
        )
        val_flow_log_rmse = float(
            val_result["flow_log_metrics"]["rmse"]
        )

        joint_score = (
            val_concentration_rmse
            + SELECTION_FLOW_LOG_RMSE_WEIGHT * val_flow_log_rmse
        )

        # 实验D的学习率调度只服务于浓度主任务。
        scheduler.step(val_concentration_rmse)
        current_lr = float(optimizer.param_groups[0]["lr"])

        val_losses = val_result["physics_losses"]

        train_logs.append({
            "epoch": epoch,
            "learning_rate": current_lr,
            "train_total_loss": train_result["total_loss"],
            "train_concentration_mse": train_result[
                "concentration_mse"
            ],
            "train_concentration_mae": train_result[
                "concentration_mae"
            ],
            "train_flow_log_mse": train_result["flow_log_mse"],
            "train_flow_log_mae": train_result["flow_log_mae"],
            "train_total_mass_loss": train_result[
                "total_mass_loss"
            ],
            "train_tracker_mass_loss": train_result[
                "tracker_mass_loss"
            ],
            # 保留原列名，实验D中它等于浓度RMSE。
            "val_selection_score": val_concentration_rmse,
            "val_joint_score": joint_score,
            "val_concentration_mae": (
                val_result["concentration_metrics"]["mae"]
            ),
            "val_concentration_rmse": val_concentration_rmse,
            "val_concentration_r2": (
                val_result["concentration_metrics"]["r2"]
            ),
            "val_flow_mae": val_result["flow_metrics"]["mae"],
            "val_flow_rmse": val_result["flow_metrics"]["rmse"],
            "val_flow_r2": val_result["flow_metrics"]["r2"],
            "val_flow_log_rmse": val_flow_log_rmse,
            "val_total_loss": val_losses["total_loss"],
            "val_total_mass_loss": val_losses["total_mass_loss"],
            "val_tracker_mass_loss": val_losses[
                "tracker_mass_loss"
            ],
        })

        # 独立保存联合任务最优检查点，不参与实验D主早停判断。
        if joint_score < best_joint_score:
            best_joint_score = joint_score
            best_joint_epoch = epoch

            torch.save(
                model.state_dict(),
                paths["best_joint_model"],
            )
            torch.save(
                make_checkpoint(
                    checkpoint_type="joint_validation_score",
                    epoch_value=best_joint_epoch,
                    selection_value=best_joint_score,
                    val_concentration_rmse_value=(
                        val_concentration_rmse
                    ),
                    val_flow_log_rmse_value=val_flow_log_rmse,
                ),
                paths["best_joint_checkpoint"],
            )

        # 主检查点只依据验证集浓度RMSE。
        if val_concentration_rmse < best_concentration_rmse:
            best_concentration_rmse = val_concentration_rmse
            best_concentration_epoch = epoch
            patience_counter = 0

            concentration_checkpoint = make_checkpoint(
                checkpoint_type="concentration_validation_rmse",
                epoch_value=best_concentration_epoch,
                selection_value=best_concentration_rmse,
                val_concentration_rmse_value=(
                    val_concentration_rmse
                ),
                val_flow_log_rmse_value=val_flow_log_rmse,
            )

            torch.save(
                model.state_dict(),
                paths["best_concentration_model"],
            )
            torch.save(
                concentration_checkpoint,
                paths["best_concentration_checkpoint"],
            )

            # 兼容原有后处理与反向设计代码。
            torch.save(
                model.state_dict(),
                paths["best_model"],
            )
            torch.save(
                concentration_checkpoint,
                paths["best_checkpoint"],
            )
        else:
            patience_counter += 1

        if epoch == 1 or epoch % 25 == 0:
            print(
                f"Epoch {epoch:04d} | "
                f"Train {train_result['total_loss']:.8f} | "
                f"ConcMSE "
                f"{train_result['concentration_mse']:.8f} | "
                f"FlowMSE {train_result['flow_log_mse']:.8f} | "
                f"Mass {train_result['total_mass_loss']:.8f} | "
                f"Tracker "
                f"{train_result['tracker_mass_loss']:.8f} | "
                f"Val Conc RMSE {val_concentration_rmse:.8f} | "
                f"Val FlowLog RMSE {val_flow_log_rmse:.8f} | "
                f"JointScore {joint_score:.8f} | "
                f"LR {current_lr:.2e} | "
                f"BestConc {best_concentration_epoch} | "
                f"BestJoint {best_joint_epoch}"
            )

        if patience_counter >= base.PATIENCE:
            print(
                "Early stopping："
                f"epoch={epoch}，"
                f"best_concentration_epoch="
                f"{best_concentration_epoch}，"
                f"best_joint_epoch={best_joint_epoch}"
            )
            break

    training_seconds = time.perf_counter() - training_start

    train_log_df = pd.DataFrame(train_logs)
    train_log_df.to_csv(
        paths["train_log"],
        index=False,
        encoding="utf-8-sig",
    )
    save_training_curve(
        train_log_df,
        paths["training_curve"],
    )

    threshold = float(
        getattr(base, "BAD_SAMPLE_THRESHOLD", 0.2)
    )

    def test_checkpoint(
        *,
        checkpoint_path: Path,
        prediction_path: Path,
        bad_sample_path: Path,
        checkpoint_label: str,
    ) -> Tuple[
        Dict[str, Any],
        Dict[str, Any],
        pd.DataFrame,
        pd.DataFrame,
        float,
    ]:
        checkpoint_payload = base.safe_torch_load(
            checkpoint_path
        )
        model.load_state_dict(
            checkpoint_payload["model_state_dict"]
        )

        inference_start_local = time.perf_counter()
        result = evaluate_dual(
            model=model,
            loader=test_loader,
            criterion=criterion,
            device=device,
        )
        inference_seconds_local = (
            time.perf_counter() - inference_start_local
        )

        prediction_dataframe = save_predictions(
            result,
            prediction_path,
        )

        bad_dataframe = prediction_dataframe.loc[
            prediction_dataframe[
                "sample_concentration_max_abs_error"
            ] >= threshold
        ].copy().sort_values(
            "sample_concentration_max_abs_error",
            ascending=False,
        )
        bad_dataframe.to_csv(
            bad_sample_path,
            index=False,
            encoding="utf-8-sig",
        )

        conc_local = result["concentration_metrics"]
        flow_local = result["flow_metrics"]
        flow_log_local = result["flow_log_metrics"]
        physics_local = result["physics_losses"]

        metric_payload: Dict[str, Any] = {
            "model": "PhysicsGuidedDualTaskGNN",
            "script_version": SCRIPT_VERSION,
            "checkpoint_label": checkpoint_label,
            "checkpoint_type": checkpoint_payload.get(
                "checkpoint_type",
                checkpoint_label,
            ),
            "seed": args.seed,
            "dataset_path": str(dataset_path),
            "dataset_sha256": dataset_hash,
            "shared_split_path": str(split_path),
            "shared_split_sha256": split_hash,
            "num_train": len(train_graphs),
            "num_val": len(val_graphs),
            "num_test": len(test_graphs),
            "balanced_sampler": use_balanced_sampler,
            "data_augmentation": False,
            "structure_disjoint_required": (
                require_structure_disjoint
            ),
            "structure_overlap_count": group_audit[
                "structure_overlap_count"
            ],
            "best_epoch": int(
                checkpoint_payload["best_epoch"]
            ),
            "best_selection_score": float(
                checkpoint_payload["best_selection_score"]
            ),
            "best_val_concentration_rmse": float(
                checkpoint_payload[
                    "best_val_concentration_rmse"
                ]
            ),
            "best_val_flow_log_rmse": float(
                checkpoint_payload["best_val_flow_log_rmse"]
            ),
            "test_concentration_mae": conc_local["mae"],
            "test_concentration_rmse": conc_local["rmse"],
            "test_concentration_r2": conc_local["r2"],
            "test_concentration_max_abs_error": conc_local[
                "max_abs_error"
            ],
            "test_flow_mae": flow_local["mae"],
            "test_flow_rmse": flow_local["rmse"],
            "test_flow_r2": flow_local["r2"],
            "test_flow_max_abs_error": flow_local[
                "max_abs_error"
            ],
            "test_flow_log_mae": flow_log_local["mae"],
            "test_flow_log_rmse": flow_log_local["rmse"],
            "test_flow_log_r2": flow_log_local["r2"],
            "test_total_loss": physics_local["total_loss"],
            "test_total_mass_loss": physics_local[
                "total_mass_loss"
            ],
            "test_tracker_mass_loss": physics_local[
                "tracker_mass_loss"
            ],
            "test_mean_abs_relative_total_mass_error": (
                physics_local[
                    "mean_abs_relative_total_mass_error"
                ]
            ),
            "test_mean_abs_relative_tracker_error": (
                physics_local[
                    "mean_abs_relative_tracker_error"
                ]
            ),
            "parameter_count": parameter_count,
            "training_seconds": training_seconds,
            "test_inference_seconds": inference_seconds_local,
            "inference_ms_per_graph": (
                inference_seconds_local
                / max(len(test_graphs), 1)
                * 1000.0
            ),
            "bad_sample_count": len(bad_dataframe),
        }

        metric_payload.update({
            f"test_concentration_{name}": value
            for name, value in result[
                "concentration_per_outlet"
            ].items()
        })
        metric_payload.update({
            f"test_flow_{name}": value
            for name, value in result[
                "flow_per_outlet"
            ].items()
        })

        return (
            checkpoint_payload,
            result,
            prediction_dataframe,
            bad_dataframe,
            inference_seconds_local,
        ), metric_payload

    (
        concentration_test_bundle,
        metrics,
    ) = test_checkpoint(
        checkpoint_path=paths["best_concentration_checkpoint"],
        prediction_path=paths["predictions"],
        bad_sample_path=paths["bad_samples"],
        checkpoint_label="concentration_best",
    )

    (
        joint_test_bundle,
        joint_metrics,
    ) = test_checkpoint(
        checkpoint_path=paths["best_joint_checkpoint"],
        prediction_path=paths["joint_predictions"],
        bad_sample_path=paths["joint_bad_samples"],
        checkpoint_label="joint_best",
    )

    total_seconds = time.perf_counter() - start_total
    metrics["total_seconds"] = total_seconds
    joint_metrics["total_seconds"] = total_seconds

    pd.DataFrame([metrics]).to_csv(
        paths["metrics_csv"],
        index=False,
        encoding="utf-8-sig",
    )
    write_json(paths["metrics_json"], metrics)

    pd.DataFrame([joint_metrics]).to_csv(
        paths["joint_metrics_csv"],
        index=False,
        encoding="utf-8-sig",
    )
    write_json(paths["joint_metrics_json"], joint_metrics)

    comparison_columns = [
        "checkpoint_label",
        "checkpoint_type",
        "best_epoch",
        "best_val_concentration_rmse",
        "best_val_flow_log_rmse",
        "test_concentration_mae",
        "test_concentration_rmse",
        "test_concentration_r2",
        "test_concentration_max_abs_error",
        "test_flow_log_rmse",
        "test_mean_abs_relative_total_mass_error",
        "test_mean_abs_relative_tracker_error",
        "bad_sample_count",
    ]
    pd.DataFrame(
        [
            {
                column: metrics.get(column)
                for column in comparison_columns
            },
            {
                column: joint_metrics.get(column)
                for column in comparison_columns
            },
        ]
    ).to_csv(
        paths["checkpoint_comparison"],
        index=False,
        encoding="utf-8-sig",
    )

    run_config = {
        "script": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "experiment_type": EXPERIMENT_TYPE,
        "seed": args.seed,
        "dataset_path": str(dataset_path),
        "dataset_sha256": dataset_hash,
        "shared_split_path": str(split_path),
        "shared_split_sha256": split_hash,
        "balanced_sampler": use_balanced_sampler,
        "data_augmentation": False,
        "primary_checkpoint": "best_concentration_checkpoint.pt",
        "joint_checkpoint": "best_joint_checkpoint.pt",
        "scheduler_metric": "val_concentration_rmse",
        "early_stopping_metric": "val_concentration_rmse",
        "require_structure_disjoint": require_structure_disjoint,
        "loss_weights": {
            "concentration_mse": LAMBDA_CONCENTRATION_MSE,
            "concentration_mae": LAMBDA_CONCENTRATION_MAE,
            "flow_log_mse": LAMBDA_FLOW_MSE,
            "flow_log_mae": LAMBDA_FLOW_MAE,
            "total_mass": LAMBDA_TOTAL_MASS,
            "tracker_mass": LAMBDA_TRACKER_MASS,
        },
        "selection_flow_log_rmse_weight": (
            SELECTION_FLOW_LOG_RMSE_WEIGHT
        ),
        "preflight": preflight,
        "group_audit": group_audit,
        "output_files": {
            name: str(path)
            for name, path in paths.items()
        },
    }
    write_json(paths["run_config"], run_config)

    report_lines = [
        "# Physics-GNN 实验D：均衡采样 + 中等辅助损失权重",
        "",
        "## 核心结构",
        "",
        "- node 2~7分别对应y1~y6和q1~q6；",
        "- chip_physics[6,7]直接来自Physics-GNN V4数据集；",
        "- 浓度头学习左右相对通导；",
        "- 流量头学习共同尺度与全局竞争；",
        "- 质量流量不作为结构输入；",
        "- 使用总质量守恒与示踪剂守恒约束；",
        "- 默认关闭均衡采样，不做数据增强；",
        "- 主检查点按验证集浓度RMSE选择；",
        "- 另存联合浓度/流量检查点用于严格对照。",
        "",
        "## 数据",
        "",
        f"- Train：{len(train_graphs)}",
        f"- Validation：{len(val_graphs)}",
        f"- Test：{len(test_graphs)}",
        f"- old/new均衡采样：{use_balanced_sampler}",
        f"- 结构交叉数量：{group_audit['structure_overlap_count']}",
        "",
        "## 浓度最优检查点测试结果（主结果）",
        "",
        f"- Best epoch：{metrics['best_epoch']}",
        f"- 浓度 MAE：{metrics['test_concentration_mae']}",
        f"- 浓度 RMSE：{metrics['test_concentration_rmse']}",
        f"- 浓度 R²：{metrics['test_concentration_r2']}",
        f"- 流量 Log-RMSE：{metrics['test_flow_log_rmse']}",
        f"- 平均总质量相对误差："
        f"{metrics['test_mean_abs_relative_total_mass_error']}",
        f"- 平均示踪剂相对误差："
        f"{metrics['test_mean_abs_relative_tracker_error']}",
        "",
        "## 联合检查点测试结果（对照）",
        "",
        f"- Best epoch：{joint_metrics['best_epoch']}",
        f"- 浓度 RMSE："
        f"{joint_metrics['test_concentration_rmse']}",
        f"- 浓度 R²：{joint_metrics['test_concentration_r2']}",
        f"- 流量 Log-RMSE："
        f"{joint_metrics['test_flow_log_rmse']}",
        f"- 平均总质量相对误差："
        f"{joint_metrics['test_mean_abs_relative_total_mass_error']}",
        f"- 平均示踪剂相对误差："
        f"{joint_metrics['test_mean_abs_relative_tracker_error']}",
        "",
        "## 输出",
        "",
        *[
            f"- {name}：`{path}`"
            for name, path in paths.items()
        ],
    ]

    paths["report"].write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print()
    print("=" * 90)
    print("Physics-GNN Experiment D Test Results")
    print("=" * 90)
    print("[主结果] 浓度最优检查点")
    print("Best Epoch：", metrics["best_epoch"])
    print(
        "Test Concentration RMSE：",
        metrics["test_concentration_rmse"],
    )
    print(
        "Test Concentration R2：",
        metrics["test_concentration_r2"],
    )
    print(
        "Test Flow Log RMSE：",
        metrics["test_flow_log_rmse"],
    )
    print(
        "Mean Relative Total Mass Error：",
        metrics["test_mean_abs_relative_total_mass_error"],
    )
    print(
        "Mean Relative Tracker Error：",
        metrics["test_mean_abs_relative_tracker_error"],
    )
    print("-" * 90)
    print("[对照] 联合检查点")
    print("Best Epoch：", joint_metrics["best_epoch"])
    print(
        "Test Concentration RMSE：",
        joint_metrics["test_concentration_rmse"],
    )
    print(
        "Test Flow Log RMSE：",
        joint_metrics["test_flow_log_rmse"],
    )
    print("Comparison：", paths["checkpoint_comparison"])
    print("Model Output：", model_dir)
    print("Report Output：", report_dir)
    print("=" * 90)


if __name__ == "__main__":
    main()
