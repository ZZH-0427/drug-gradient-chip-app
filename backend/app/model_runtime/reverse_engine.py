# -*- coding: utf-8 -*-
from __future__ import annotations

"""
inverse_design_tandem_physics_gnn_v3_project_structure.py
=========================================================

Physics-GNN 确定性反向设计程序。

功能
----
输入第一种目标浓度表：

    浓度出口位置,inlet1,inlet2,y1,y2,y3,y4,y5,y6
    出口浓度,1,0,0.25,0.23,0.26,0.45,0.66,0.83

inlet1 和 inlet2 必须在输入表中逐行提供。
程序不再默认哪一侧是高浓度入口，例如以下两种输入都支持：

    出口浓度,1,0,0.25,0.23,0.26,0.45,0.66,0.83
    出口浓度,0,1,0.75,0.77,0.74,0.55,0.34,0.17

输出第二种结构表：

    # ,inlet1,inlet2,P1-...,弯曲直道距离,位置,...,P12-...,弯曲直道距离,位置
    名称,,,P1,,,P2,...,P12,,
    DP 0,1,0,预测宽度,预测距离,1,...,预测宽度,预测距离,6

算法
----
1. 加载并冻结已训练好的 Physics-GNN 正向检查点；
2. 对每组目标浓度建立一组可优化的结构变量；
3. 宽度通过 sigmoid 严格限制在 0.1~0.3 mm；
4. 左右弯曲数从 1~6 中确定性选择，对应距离：
       1 -> 7 mm
       2 -> 13 mm
       3 -> 19 mm
       4 -> 25 mm
       5 -> 31 mm
       6 -> 37 mm
5. 将结构构造成与正向训练完全一致的 8节点/24边 图；
6. 用冻结的 Physics-GNN 预测浓度，反向更新结构变量；
7. 将弯曲数离散化后，再只优化宽度进行精修；
8. 固定随机种子和唯一性代价，最终每个目标只输出一个结构。

说明
----
本程序采用“确定性串联反向优化”：
    inlet1/inlet2 + 目标浓度 -> 结构参数
    -> 冻结Physics-GNN -> 预测浓度 -> 优化结构

入口浓度由输入表逐行读取。初始宽度依据 inlet1 在目标浓度中的混合比例生成，
因此 inlet1 或 inlet2 任意一侧都可以是高浓度入口。

它不需要先训练一个新的逆向MLP，拿到正式A6正向检查点后即可运行。
当以后需要一次预测大量目标时，可以把本程序生成的数据用于训练逆向MLP进行加速。

依赖
----
    pip install torch pandas numpy torch-geometric

项目目录结构
------------
项目根目录/
├─ 正向预测与反向预测/
│  ├─ 反向预测/
│  │  ├─ 反向预测输入/
│  │  │  └─ 反向预测输入.csv
│  │  ├─ 反向预测输出/              # 程序自动创建
│  │  └─ inverse_design_tandem_physics_gnn_v3_project_structure.py
│  └─ 正向预测/
└─ 其他训练与模型目录/

默认运行
--------
脚本会自动识别自身位置，因此可以在任何工作目录中运行：

python inverse_design_tandem_physics_gnn_v3_project_structure.py

默认输入：
    脚本所在目录/反向预测输入/反向预测输入.csv

默认输出：
    脚本所在目录/反向预测输出/

默认检查点搜索顺序：
    1. 正向预测与反向预测/正向预测/
    2. 整个项目根目录/

手动指定检查点：
python inverse_design_tandem_physics_gnn_v3_project_structure.py ^
    --checkpoint "D:/项目/GNN/消融实验/A6/model/seed_42/best_A6_checkpoint.pt"

快速测试：
python inverse_design_tandem_physics_gnn_v3_project_structure.py ^
    --steps 400 ^
    --refine-steps 120 ^
    --restarts 2

只检查默认输入表：
python inverse_design_tandem_physics_gnn_v3_project_structure.py ^
    --dry-run
"""

import argparse
import hashlib
import json
import math
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import Tensor, nn

try:
    from torch_geometric.nn import TransformerConv, global_mean_pool
except ImportError:
    TransformerConv = None
    global_mean_pool = None
# =============================================================================
# 0. 固定结构与默认参数
# =============================================================================

CHIP_COUNT = 6
NODE_COUNT = 8
NODE_FEATURE_DIM = 15
EDGE_COUNT = 24
EDGE_FEATURE_DIM = 9
GLOBAL_FEATURE_DIM = 2
CHIP_PHYSICS_DIM = 7

INLET1_INDEX = 0
INLET2_INDEX = 1
CHIP_NODE_START = 2

DEFAULT_WIDTH_MIN_MM = 0.1
DEFAULT_WIDTH_MAX_MM = 0.3

DEFAULT_BEND_VALUES = (1, 2, 3, 4, 5, 6)
DEFAULT_DISTANCE_VALUES_MM = (7.0, 13.0, 19.0, 25.0, 31.0, 37.0)

TARGET_COLUMNS = ("y1", "y2", "y3", "y4", "y5", "y6")
EPS = 1.0e-12
FLOW_EPS = 1.0e-18

# -----------------------------------------------------------------------------
# 项目路径：完全按照当前文件夹结构解析，不依赖启动程序时的工作目录。
#
# 项目根目录/
# └─ 正向预测与反向预测/
#    ├─ 反向预测/
#    │  ├─ 反向预测输入/反向预测输入.csv
#    │  ├─ 反向预测输出/
#    │  └─ 本脚本
#    └─ 正向预测/
# -----------------------------------------------------------------------------
SCRIPT_FILE = Path(__file__).resolve()
INVERSE_PREDICTION_DIR = SCRIPT_FILE.parent
FORWARD_AND_INVERSE_DIR = INVERSE_PREDICTION_DIR.parent
PROJECT_ROOT = FORWARD_AND_INVERSE_DIR.parent
APP_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_TARGET_FILE = (
    INVERSE_PREDICTION_DIR
    / "反向预测输入"
    / "反向预测输入.csv"
)
DEFAULT_OUTPUT_DIR = (
    INVERSE_PREDICTION_DIR
    / "反向预测输出"
)
DEFAULT_FORWARD_PREDICTION_DIR = (
    FORWARD_AND_INVERSE_DIR
    / "正向预测"
)


# =============================================================================
# 1. 工具
# =============================================================================

DEFAULT_BUNDLED_CHECKPOINT = (
    APP_ROOT
    / "model_assets"
    / "physics_gnn"
    / "best_concentration_checkpoint.pt"
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def safe_torch_load(path: Path) -> Any:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def parse_float_list(text: str) -> Tuple[float, ...]:
    values = tuple(float(item.strip()) for item in text.split(",") if item.strip())
    if not values:
        raise argparse.ArgumentTypeError("列表不能为空。")
    return values


def inverse_sigmoid(value: Tensor) -> Tensor:
    value = value.clamp(1.0e-5, 1.0 - 1.0e-5)
    return torch.log(value / (1.0 - value))


def rankdata(values: np.ndarray) -> np.ndarray:
    """不依赖scipy的平均秩。"""
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def spearman_correlation(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 2 or b.size < 2:
        return float("nan")
    ra = rankdata(a)
    rb = rankdata(b)
    if np.std(ra) < 1.0e-15 or np.std(rb) < 1.0e-15:
        return 1.0 if np.allclose(a, b) else 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def validate_positive_std(std: Tensor) -> Tensor:
    return torch.where(std.abs() < 1.0e-12, torch.ones_like(std), std)


# =============================================================================
# 2. 目标浓度输入
# =============================================================================

@dataclass(frozen=True)
class TargetSample:
    name: str
    inlet1: float
    inlet2: float
    concentration: np.ndarray


def read_target_table(path: Path) -> List[TargetSample]:
    if not path.is_file():
        raise FileNotFoundError(
            f"目标浓度文件不存在：{path}\n"
            "请将输入表放在：\n"
            f"  {DEFAULT_TARGET_FILE}\n"
            "或者使用 --target 手动指定文件。"
        )

    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(path, encoding="gbk")
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        raise ValueError("目标浓度表仅支持 CSV、XLSX、XLS。")

    normalized = {
        str(column).strip().lower(): column
        for column in frame.columns
    }

    required_columns = ("inlet1", "inlet2", *TARGET_COLUMNS)
    missing = [name for name in required_columns if name not in normalized]
    if missing:
        raise KeyError(
            "输入表缺少必填列："
            + ", ".join(missing)
            + "\n要求列名为 inlet1,inlet2,y1,y2,y3,y4,y5,y6。"
        )

    label_column: Optional[Any] = None
    for candidate in ("浓度出口位置", "名称", "name", "sample", "#", "# "):
        if candidate in frame.columns:
            label_column = candidate
            break

    targets: List[TargetSample] = []

    for row_index, row in frame.iterrows():
        try:
            inlet1 = float(row[normalized["inlet1"]])
            inlet2 = float(row[normalized["inlet2"]])
            values = np.asarray(
                [float(row[normalized[name]]) for name in TARGET_COLUMNS],
                dtype=np.float32,
            )
        except (TypeError, ValueError):
            continue

        if not np.isfinite(values).all():
            continue
        if not np.isfinite(inlet1) or not np.isfinite(inlet2):
            continue
        if math.isclose(inlet1, inlet2, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(
                f"第 {row_index + 2} 行 inlet1 与 inlet2 相同（{inlet1}）。"
                "两入口浓度相同，无法通过混合设计得到不同出口浓度。"
            )

        lower = min(inlet1, inlet2)
        upper = max(inlet1, inlet2)
        outside = (values < lower - 1.0e-6) | (values > upper + 1.0e-6)
        if outside.any():
            bad_columns = [
                TARGET_COLUMNS[index]
                for index in np.where(outside)[0].tolist()
            ]
            warnings.warn(
                f"第 {row_index + 2} 行目标浓度 {bad_columns} 超出入口浓度范围 "
                f"[{lower}, {upper}]；这通常在纯混合条件下不可实现，程序仍会运行。",
                RuntimeWarning,
            )

        if label_column is not None and pd.notna(row[label_column]):
            sample_name = str(row[label_column]).strip()
        else:
            sample_name = f"target_{len(targets)}"

        targets.append(
            TargetSample(
                name=sample_name or f"target_{len(targets)}",
                inlet1=inlet1,
                inlet2=inlet2,
                concentration=values,
            )
        )

    if not targets:
        raise ValueError(
            "目标浓度表中没有找到有效的 inlet1、inlet2、y1~y6 数值行。"
        )

    return targets


# =============================================================================
# 3. 正向模型
# =============================================================================

class LegacyPhysicsGNNTransformer(nn.Module):
    """兼容旧版 full Physics-GNN 单浓度输出检查点。"""

    def __init__(
        self,
        *,
        in_channels: int,
        edge_dim: int,
        global_feature_dim: int,
        hidden_channels: int,
        output_dim: int,
        heads: int,
        num_layers: int,
        dropout: float,
        use_edge_attr: bool,
        use_u: bool,
    ) -> None:
        super().__init__()

        if TransformerConv is None or global_mean_pool is None:
            raise ImportError("需要安装 torch-geometric。")

        self.use_edge_attr = bool(use_edge_attr)
        self.use_u = bool(use_u)
        self.global_feature_dim = int(global_feature_dim)

        self.input_projection = nn.Linear(in_channels, hidden_channels)
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
        fused_dim = hidden_channels + global_feature_dim

        self.regression_head = nn.Sequential(
            nn.Linear(fused_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.LayerNorm(hidden_channels // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels // 2, output_dim),
        )

    def forward(self, data: Any) -> Tensor:
        x = F.gelu(self.input_projection(data.x))

        for conv, norm in zip(self.convs, self.norms):
            residual = x
            if self.use_edge_attr:
                message = conv(x, data.edge_index, data.edge_attr)
            else:
                message = conv(x, data.edge_index)
            message = self.dropout(F.gelu(norm(message)))
            x = residual + message

        graph_embedding = global_mean_pool(x, data.batch)

        if self.use_u:
            global_features = data.u.reshape(data.num_graphs, -1)
        else:
            global_features = torch.zeros(
                (data.num_graphs, self.global_feature_dim),
                dtype=graph_embedding.dtype,
                device=graph_embedding.device,
            )

        fused = torch.cat([graph_embedding, global_features], dim=1)
        return self.regression_head(fused)


class PhysicsGuidedDualTaskGNN(nn.Module):
    """与A6双任务Physics-GNN一致的浓度+流量模型。"""

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

        if TransformerConv is None:
            raise ImportError("需要安装 torch-geometric。")

        self.in_channels = int(in_channels)
        self.edge_dim = int(edge_dim)
        self.global_feature_dim = int(global_feature_dim)
        self.hidden_channels = int(hidden_channels)
        self.use_edge_attr = bool(use_edge_attr)

        self.register_buffer("x_mean", x_mean.detach().float().reshape(1, -1))
        self.register_buffer("x_std", x_std.detach().float().reshape(1, -1))
        self.register_buffer("u_mean", u_mean.detach().float().reshape(1, -1))
        self.register_buffer("u_std", u_std.detach().float().reshape(1, -1))
        self.register_buffer(
            "flow_log_mean",
            flow_log_mean.detach().float().reshape(1),
        )
        self.register_buffer(
            "flow_log_std",
            flow_log_std.detach().float().reshape(1),
        )

        self.input_projection = nn.Linear(
            in_channels + CHIP_PHYSICS_DIM,
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

        self.raw_width_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.raw_distance_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.local_concentration_bias = nn.Parameter(torch.zeros(1))
        self.concentration_global_gate = nn.Parameter(torch.tensor(-2.0))

        context_dim = (
            hidden_channels
            + hidden_channels
            + CHIP_PHYSICS_DIM
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
        flow_log = flow_log_z * self.flow_log_std + self.flow_log_mean
        return torch.exp(flow_log).clamp_min(FLOW_EPS)

    def forward(self, data: Any) -> Dict[str, Tensor]:
        graph_count = int(data.num_graphs)

        node_x = data.x.reshape(
            graph_count,
            NODE_COUNT,
            self.in_channels,
        )

        chip_physics_z = data.chip_physics_z.reshape(
            graph_count,
            CHIP_COUNT,
            CHIP_PHYSICS_DIM,
        )
        chip_physics_raw = data.chip_physics.reshape(
            graph_count,
            CHIP_COUNT,
            CHIP_PHYSICS_DIM,
        )

        physics_for_nodes = torch.zeros(
            (
                graph_count,
                NODE_COUNT,
                CHIP_PHYSICS_DIM,
            ),
            dtype=node_x.dtype,
            device=node_x.device,
        )
        physics_for_nodes[:, CHIP_NODE_START:, :] = chip_physics_z

        node_input = torch.cat(
            [node_x, physics_for_nodes],
            dim=2,
        ).reshape(graph_count * NODE_COUNT, -1)

        hidden = F.gelu(self.input_projection(node_input))

        for conv, norm in zip(self.convs, self.norms):
            residual = hidden
            if self.use_edge_attr:
                message = conv(hidden, data.edge_index, data.edge_attr)
            else:
                message = conv(hidden, data.edge_index)
            hidden = residual + self.dropout(F.gelu(norm(message)))

        node_hidden = hidden.reshape(
            graph_count,
            NODE_COUNT,
            self.hidden_channels,
        )

        chip_hidden = node_hidden[:, CHIP_NODE_START:, :]
        graph_context = node_hidden.mean(dim=1, keepdim=True).expand(
            -1,
            CHIP_COUNT,
            -1,
        )

        normalized_u = data.u.reshape(graph_count, -1)
        raw_u = self.recover_raw_u(normalized_u)
        u_context = raw_u.unsqueeze(1).expand(-1, CHIP_COUNT, -1)

        context = torch.cat(
            [chip_hidden, graph_context, chip_physics_z, u_context],
            dim=2,
        )

        width_weight = F.softplus(self.raw_width_ratio_weight)
        distance_weight = F.softplus(self.raw_distance_ratio_weight)

        local_logit = (
            self.local_concentration_bias
            + width_weight * chip_physics_raw[:, :, 0]
            + distance_weight * chip_physics_raw[:, :, 4]
        )

        correction = self.concentration_correction_head(context).squeeze(-1)
        gate = torch.sigmoid(self.concentration_global_gate)
        alpha = torch.sigmoid(local_logit + gate * correction)

        inlet1 = raw_u[:, 0:1]
        inlet2 = raw_u[:, 1:2]
        concentration = inlet2 + alpha * (inlet1 - inlet2)

        flow_log_z = self.flow_head(context).squeeze(-1)
        flow = self.decode_flow(flow_log_z)

        return {
            "concentration": concentration,
            "flow_log_z": flow_log_z,
            "flow": flow,
            "mixing_fraction": alpha,
            "raw_u": raw_u,
        }


@dataclass
class LoadedForwardModel:
    model: nn.Module
    checkpoint: Dict[str, Any]
    normalizers: Dict[str, Tensor]
    model_type: str
    checkpoint_path: Path


def checkpoint_search_roots(
    explicit_search_root: Optional[Path],
) -> List[Path]:
    """
    按优先级给出检查点搜索目录。

    1. 用户通过 --search-root 指定的目录；
    2. 正向预测与反向预测/正向预测；
    3. 项目根目录。

    使用 resolve 后去重，目录不存在时自动跳过。
    """
    candidates: List[Path] = []

    if explicit_search_root is not None:
        candidates.append(explicit_search_root)

    candidates.extend(
        [
            DEFAULT_FORWARD_PREDICTION_DIR,
            PROJECT_ROOT,
        ]
    )

    roots: List[Path] = []
    seen: set[str] = set()

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        key = str(resolved).lower()

        if key in seen:
            continue
        seen.add(key)

        if resolved.is_dir():
            roots.append(resolved)

    return roots


def find_best_checkpoint(
    search_roots: Sequence[Path],
) -> Path:
    """
    在多个目录中寻找可用于反向设计的正式正向检查点。

    优先选择文件名明确属于A6/双任务Physics-GNN的检查点；
    同一优先级内，选择检查点记录的验证集浓度RMSE最低者。
    """
    candidate_patterns: Tuple[Tuple[int, str], ...] = (
        (0, "**/best_A6_checkpoint.pt"),
        (1, "**/*A6*checkpoint*.pt"),
        (2, "**/best_dualtask_checkpoint.pt"),
        (3, "**/*dualtask*checkpoint*.pt"),
        (4, "**/best_ablation_checkpoint.pt"),
    )

    found: Dict[Path, int] = {}

    for root in search_roots:
        for priority, pattern in candidate_patterns:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                current = found.get(resolved)
                if current is None or priority < current:
                    found[resolved] = priority

    if not found:
        searched = "\n".join(f"  - {root}" for root in search_roots)
        raise FileNotFoundError(
            "没有自动找到可用的Physics-GNN检查点。\n"
            "已搜索目录：\n"
            f"{searched or '  （没有有效搜索目录）'}\n"
            "请确认正式检查点位于项目内，或使用：\n"
            "  --checkpoint \"完整路径/best_A6_checkpoint.pt\""
        )

    scored: List[Tuple[int, float, str, Path]] = []

    for path, filename_priority in found.items():
        try:
            payload = safe_torch_load(path)
            if not isinstance(payload, Mapping):
                continue

            score_raw = payload.get(
                "best_val_concentration_rmse",
                payload.get(
                    "best_selection_score",
                    payload.get(
                        "best_val_rmse",
                        float("inf"),
                    ),
                ),
            )

            score = float(score_raw)
            if not math.isfinite(score):
                score = float("inf")

            scored.append(
                (
                    filename_priority,
                    score,
                    str(path).lower(),
                    path,
                )
            )
        except Exception as exc:
            warnings.warn(
                f"跳过无法读取的检查点 {path}：{exc}",
                RuntimeWarning,
            )

    if not scored:
        raise RuntimeError(
            "找到了候选检查点文件，但没有一个包含可读取的模型检查点内容。"
        )

    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return scored[0][3]


def load_forward_model(
    checkpoint_path: Path,
    device: torch.device,
) -> LoadedForwardModel:
    if TransformerConv is None:
        raise ImportError(
            "正式反向预测需要安装 torch-geometric：\n"
            "pip install torch-geometric"
        )

    raw = safe_torch_load(checkpoint_path)
    if not isinstance(raw, Mapping):
        raise TypeError("检查点内容不是字典。")

    checkpoint = dict(raw)
    architecture = dict(checkpoint.get("architecture", {}))
    state_dict = checkpoint.get("model_state_dict")
    normalizers_raw = checkpoint.get("normalizers")

    if not isinstance(state_dict, Mapping):
        raise KeyError("检查点缺少 model_state_dict。")
    if not isinstance(normalizers_raw, Mapping):
        raise KeyError("检查点缺少 normalizers。")

    normalizers = {
        key: torch.as_tensor(value).float()
        for key, value in normalizers_raw.items()
    }

    model_type = str(architecture.get("model_type", "")).strip()

    is_dualtask = (
        model_type == "PhysicsGuidedDualTaskGNN"
        or "chip_physics_mean" in normalizers
        or "flow_log_mean" in normalizers
    )

    if is_dualtask:
        required = (
            "x_mean",
            "x_std",
            "edge_mean",
            "edge_std",
            "u_mean",
            "u_std",
            "chip_physics_mean",
            "chip_physics_std",
            "flow_log_mean",
            "flow_log_std",
        )
        missing = [name for name in required if name not in normalizers]
        if missing:
            raise KeyError(
                "A6双任务检查点缺少标准化参数："
                + ", ".join(missing)
            )

        model = PhysicsGuidedDualTaskGNN(
            in_channels=int(architecture.get("in_channels", NODE_FEATURE_DIM)),
            edge_dim=int(architecture.get("edge_dim", EDGE_FEATURE_DIM)),
            global_feature_dim=int(
                architecture.get("global_feature_dim", GLOBAL_FEATURE_DIM)
            ),
            hidden_channels=int(architecture.get("hidden_channels", 128)),
            heads=int(architecture.get("heads", 4)),
            num_layers=int(
                architecture.get("layers", architecture.get("num_layers", 3))
            ),
            dropout=float(architecture.get("dropout", 0.1)),
            use_edge_attr=bool(architecture.get("use_edge_attr", True)),
            x_mean=normalizers["x_mean"],
            x_std=normalizers["x_std"],
            u_mean=normalizers["u_mean"],
            u_std=normalizers["u_std"],
            flow_log_mean=normalizers["flow_log_mean"],
            flow_log_std=normalizers["flow_log_std"],
        )
        resolved_type = "PhysicsGuidedDualTaskGNN"
    else:
        required = (
            "x_mean",
            "x_std",
            "edge_mean",
            "edge_std",
            "u_mean",
            "u_std",
        )
        missing = [name for name in required if name not in normalizers]
        if missing:
            raise KeyError(
                "旧版Physics-GNN检查点缺少标准化参数："
                + ", ".join(missing)
            )

        model = LegacyPhysicsGNNTransformer(
            in_channels=int(architecture.get("in_channels", NODE_FEATURE_DIM)),
            edge_dim=int(architecture.get("edge_dim", EDGE_FEATURE_DIM)),
            global_feature_dim=int(
                architecture.get("global_feature_dim", GLOBAL_FEATURE_DIM)
            ),
            hidden_channels=int(architecture.get("hidden_channels", 128)),
            output_dim=CHIP_COUNT,
            heads=int(architecture.get("heads", 4)),
            num_layers=int(
                architecture.get("layers", architecture.get("num_layers", 3))
            ),
            dropout=float(architecture.get("dropout", 0.1)),
            use_edge_attr=bool(architecture.get("use_edge_attr", True)),
            use_u=bool(architecture.get("use_u", True)),
        )
        resolved_type = "LegacyPhysicsGNNTransformer"

    model.load_state_dict(dict(state_dict), strict=True)
    model.to(device)
    model.eval()

    for parameter in model.parameters():
        parameter.requires_grad_(False)

    return LoadedForwardModel(
        model=model,
        checkpoint=checkpoint,
        normalizers=normalizers,
        model_type=resolved_type,
        checkpoint_path=checkpoint_path,
    )


# =============================================================================
# 4. 可微图构建
# =============================================================================

def normalize(
    value: Tensor,
    mean: Tensor,
    std: Tensor,
) -> Tensor:
    mean = mean.to(device=value.device, dtype=value.dtype).reshape(
        *((1,) * (value.ndim - 1)),
        -1,
    )
    std = validate_positive_std(
        std.to(device=value.device, dtype=value.dtype)
    ).reshape(*((1,) * (value.ndim - 1)), -1)
    return (value - mean) / std


def build_chip_physics(
    widths: Tensor,
    distances: Tensor,
) -> Tensor:
    left_width = widths[:, :, 0]
    right_width = widths[:, :, 1]
    left_distance = distances[:, :, 0]
    right_distance = distances[:, :, 1]

    width_sum = left_width + right_width
    distance_sum = left_distance + right_distance

    return torch.stack(
        [
            torch.log((left_width + EPS) / (right_width + EPS)),
            (left_width - right_width) / (width_sum + EPS),
            torch.sqrt((left_width * right_width).clamp_min(EPS)),
            width_sum,
            torch.log((right_distance + EPS) / (left_distance + EPS)),
            (right_distance - left_distance) / (distance_sum + EPS),
            torch.sqrt((left_distance * right_distance).clamp_min(EPS)),
        ],
        dim=2,
    )


def build_differentiable_graph(
    *,
    widths: Tensor,
    bend_values: Tensor,
    loaded: LoadedForwardModel,
    inlet1: float,
    inlet2: float,
) -> SimpleNamespace:
    """
    widths:     [B, 6, 2]
    bend_values:[B, 6, 2]，可为连续期望弯曲数或最终整数弯曲数。
    """

    device = widths.device
    dtype = widths.dtype
    batch_size = int(widths.shape[0])

    distances = 1.0 + 6.0 * bend_values

    raw_x = torch.zeros(
        (batch_size, NODE_COUNT, NODE_FEATURE_DIM),
        device=device,
        dtype=dtype,
    )

    # inlet1 node
    raw_x[:, 0, 0] = 1.0
    raw_x[:, 0, 3] = float(inlet1)

    # inlet2 node
    raw_x[:, 1, 1] = 1.0
    raw_x[:, 1, 3] = float(inlet2)

    chip_indices = torch.arange(
        CHIP_COUNT,
        device=device,
        dtype=dtype,
    )
    assembly_norm = chip_indices / float(CHIP_COUNT - 1)
    positions = chip_indices + 1.0

    left_bend = bend_values[:, :, 0]
    right_bend = bend_values[:, :, 1]
    signed_span = right_bend - left_bend

    raw_x[:, CHIP_NODE_START:, 2] = 1.0
    raw_x[:, CHIP_NODE_START:, 4] = widths[:, :, 0]
    raw_x[:, CHIP_NODE_START:, 5] = widths[:, :, 1]
    raw_x[:, CHIP_NODE_START:, 6] = distances[:, :, 0]
    raw_x[:, CHIP_NODE_START:, 7] = distances[:, :, 1]
    raw_x[:, CHIP_NODE_START:, 8] = positions.unsqueeze(0)
    raw_x[:, CHIP_NODE_START:, 9] = positions.unsqueeze(0)
    raw_x[:, CHIP_NODE_START:, 10] = assembly_norm.unsqueeze(0)
    raw_x[:, CHIP_NODE_START:, 11] = left_bend / 6.0
    raw_x[:, CHIP_NODE_START:, 12] = right_bend / 6.0
    raw_x[:, CHIP_NODE_START:, 13] = signed_span / 5.0
    raw_x[:, CHIP_NODE_START:, 14] = signed_span.abs() / 5.0

    edge_sources: List[int] = []
    edge_targets: List[int] = []
    raw_edge_rows: List[Tensor] = []

    for graph_index in range(batch_size):
        offset = graph_index * NODE_COUNT

        for chip_index in range(CHIP_COUNT):
            chip_node = offset + CHIP_NODE_START + chip_index
            assembly = assembly_norm[chip_index]
            signed = signed_span[graph_index, chip_index] / 5.0
            absolute = signed.abs()

            left_width = widths[graph_index, chip_index, 0]
            right_width = widths[graph_index, chip_index, 1]
            left_distance = distances[graph_index, chip_index, 0]
            right_distance = distances[graph_index, chip_index, 1]

            # inlet1 -> chip
            edge_sources.append(offset + INLET1_INDEX)
            edge_targets.append(chip_node)
            raw_edge_rows.append(
                torch.stack(
                    [
                        left_width,
                        left_distance,
                        assembly,
                        signed,
                        absolute,
                        torch.ones((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                    ]
                )
            )

            # inlet2 -> chip
            edge_sources.append(offset + INLET2_INDEX)
            edge_targets.append(chip_node)
            raw_edge_rows.append(
                torch.stack(
                    [
                        right_width,
                        right_distance,
                        assembly,
                        signed,
                        absolute,
                        torch.zeros((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                    ]
                )
            )

            # chip -> inlet1
            edge_sources.append(chip_node)
            edge_targets.append(offset + INLET1_INDEX)
            raw_edge_rows.append(
                torch.stack(
                    [
                        left_width,
                        left_distance,
                        assembly,
                        signed,
                        absolute,
                        torch.ones((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                    ]
                )
            )

            # chip -> inlet2
            edge_sources.append(chip_node)
            edge_targets.append(offset + INLET2_INDEX)
            raw_edge_rows.append(
                torch.stack(
                    [
                        right_width,
                        right_distance,
                        assembly,
                        signed,
                        absolute,
                        torch.zeros((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                        torch.zeros((), device=device, dtype=dtype),
                        torch.ones((), device=device, dtype=dtype),
                    ]
                )
            )

    raw_edge_attr = torch.stack(raw_edge_rows, dim=0)
    edge_index = torch.tensor(
        [edge_sources, edge_targets],
        dtype=torch.long,
        device=device,
    )

    raw_u = torch.tensor(
        [[float(inlet1), float(inlet2)]],
        dtype=dtype,
        device=device,
    ).repeat(batch_size, 1)

    normalizers = loaded.normalizers

    x = normalize(
        raw_x.reshape(-1, NODE_FEATURE_DIM),
        normalizers["x_mean"],
        normalizers["x_std"],
    )
    edge_attr = normalize(
        raw_edge_attr,
        normalizers["edge_mean"],
        normalizers["edge_std"],
    )
    u = normalize(
        raw_u,
        normalizers["u_mean"],
        normalizers["u_std"],
    )

    batch_vector = torch.arange(
        batch_size,
        device=device,
        dtype=torch.long,
    ).repeat_interleave(NODE_COUNT)

    payload: Dict[str, Any] = {
        "x": x,
        "edge_index": edge_index,
        "edge_attr": edge_attr,
        "u": u,
        "batch": batch_vector,
        "num_graphs": batch_size,
    }

    if loaded.model_type == "PhysicsGuidedDualTaskGNN":
        chip_physics = build_chip_physics(widths, distances)
        chip_physics_z = normalize(
            chip_physics,
            normalizers["chip_physics_mean"],
            normalizers["chip_physics_std"],
        )
        payload["chip_physics"] = chip_physics
        payload["chip_physics_z"] = chip_physics_z

    return SimpleNamespace(**payload)


def forward_predict(
    *,
    loaded: LoadedForwardModel,
    widths: Tensor,
    bend_values: Tensor,
    inlet1: float,
    inlet2: float,
) -> Tuple[Tensor, Optional[Tensor]]:
    graph = build_differentiable_graph(
        widths=widths,
        bend_values=bend_values,
        loaded=loaded,
        inlet1=inlet1,
        inlet2=inlet2,
    )

    output = loaded.model(graph)

    if isinstance(output, Mapping):
        concentration = output["concentration"]
        flow = output.get("flow")
    else:
        concentration = output
        flow = None

    return concentration, flow


# =============================================================================
# 5. 反向优化
# =============================================================================

@dataclass
class DesignResult:
    sample_name: str
    inlet1: float
    inlet2: float
    target: np.ndarray
    predicted: np.ndarray
    flow: Optional[np.ndarray]
    widths: np.ndarray
    bends: np.ndarray
    distances: np.ndarray
    mae: float
    rmse: float
    maxae: float
    spearman: float
    screening_pass: bool
    restart_index: int
    objective: float


def decode_widths(
    raw_width: Tensor,
    width_min: float,
    width_max: float,
) -> Tensor:
    return width_min + (width_max - width_min) * torch.sigmoid(raw_width)


def initialize_raw_width(
    target: Tensor,
    *,
    inlet1: float,
    inlet2: float,
    width_min: float,
    width_max: float,
    restart_index: int,
    seed: int,
) -> Tensor:
    """
    依据 inlet1 的目标混合比例初始化左右宽度。

    正向模型使用：
        concentration = inlet2 + alpha * (inlet1 - inlet2)

    因此：
        alpha = (target - inlet2) / (inlet1 - inlet2)

    alpha 越大，初值越偏向 inlet1 侧通道；
    无论 inlet1 或 inlet2 哪一侧是高浓度入口，该关系都成立。
    """
    target = target.reshape(CHIP_COUNT)
    denominator = float(inlet1) - float(inlet2)
    if abs(denominator) < 1.0e-12:
        raise ValueError("inlet1 与 inlet2 不能相同。")

    alpha = ((target - float(inlet2)) / denominator).clamp(0.0, 1.0)
    left = width_min + (width_max - width_min) * alpha
    right = width_max - (width_max - width_min) * alpha

    if restart_index % 3 == 1:
        left = torch.full_like(left, (width_min + width_max) / 2.0)
        right = torch.full_like(right, (width_min + width_max) / 2.0)
    elif restart_index % 3 == 2:
        left, right = right, left

    generator = torch.Generator(device=target.device)
    generator.manual_seed(seed + restart_index * 1009)
    noise = 0.015 * torch.randn(
        (CHIP_COUNT, 2),
        generator=generator,
        device=target.device,
        dtype=target.dtype,
    )

    widths = torch.stack([left, right], dim=1)
    widths = (widths + noise).clamp(
        width_min + 1.0e-4,
        width_max - 1.0e-4,
    )
    scaled = (widths - width_min) / (width_max - width_min)
    return inverse_sigmoid(scaled)


def initialize_bend_logits(
    *,
    device: torch.device,
    dtype: torch.dtype,
    restart_index: int,
) -> Tensor:
    logits = torch.zeros(
        (CHIP_COUNT, 2, len(DEFAULT_BEND_VALUES)),
        device=device,
        dtype=dtype,
    )

    preferred = 2 + (restart_index % 3)  # 初始偏向3/4/5附近
    preferred = max(0, min(preferred, len(DEFAULT_BEND_VALUES) - 1))
    logits[:, :, preferred] = 1.5

    # 左右侧略微错开，避免完全对称。
    logits[:, 0, max(0, preferred - 1)] += 0.25
    logits[:, 1, min(len(DEFAULT_BEND_VALUES) - 1, preferred + 1)] += 0.25
    return logits


def compute_metrics(
    target: np.ndarray,
    predicted: np.ndarray,
) -> Tuple[float, float, float, float]:
    error = predicted - target
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error ** 2)))
    maxae = float(np.max(np.abs(error)))
    spearman = spearman_correlation(target, predicted)
    return mae, rmse, maxae, spearman


def optimize_one_target(
    *,
    sample: TargetSample,
    loaded: LoadedForwardModel,
    device: torch.device,
    width_min: float,
    width_max: float,
    steps: int,
    refine_steps: int,
    learning_rate: float,
    restarts: int,
    seed: int,
    temperature_start: float,
    temperature_end: float,
    lambda_mae: float,
    lambda_width_center: float,
    lambda_bend_complexity: float,
    lambda_entropy: float,
    min_mean_flow: float,
    screening_mae: float,
    screening_rmse: float,
    screening_maxae: float,
    screening_spearman: float,
    log_every: int,
) -> DesignResult:
    target = torch.tensor(
        sample.concentration,
        dtype=torch.float32,
        device=device,
    ).reshape(1, CHIP_COUNT)

    inlet1 = float(sample.inlet1)
    inlet2 = float(sample.inlet2)

    bend_classes = torch.tensor(
        DEFAULT_BEND_VALUES,
        dtype=torch.float32,
        device=device,
    )

    best: Optional[DesignResult] = None

    for restart_index in range(restarts):
        raw_width = nn.Parameter(
            initialize_raw_width(
                target[0],
                inlet1=inlet1,
                inlet2=inlet2,
                width_min=width_min,
                width_max=width_max,
                restart_index=restart_index,
                seed=seed,
            )
        )

        bend_logits = nn.Parameter(
            initialize_bend_logits(
                device=device,
                dtype=torch.float32,
                restart_index=restart_index,
            )
        )

        optimizer = torch.optim.Adam(
            [raw_width, bend_logits],
            lr=learning_rate,
        )

        for step in range(steps):
            fraction = step / max(steps - 1, 1)
            temperature = (
                temperature_start
                * (temperature_end / temperature_start) ** fraction
            )

            widths = decode_widths(
                raw_width,
                width_min,
                width_max,
            ).unsqueeze(0)

            bend_probability = F.softmax(
                bend_logits / temperature,
                dim=-1,
            )
            bend_expected = torch.sum(
                bend_probability * bend_classes,
                dim=-1,
            ).unsqueeze(0)

            prediction, flow = forward_predict(
                loaded=loaded,
                widths=widths,
                bend_values=bend_expected,
                inlet1=inlet1,
                inlet2=inlet2,
            )

            concentration_mse = F.mse_loss(prediction, target)
            concentration_mae = F.l1_loss(prediction, target)

            width_center = (width_min + width_max) / 2.0
            half_range = (width_max - width_min) / 2.0
            width_center_loss = torch.mean(
                ((widths - width_center) / max(half_range, EPS)) ** 2
            )

            bend_complexity = torch.mean(
                (bend_expected - 1.0) / 5.0
            )

            entropy = -torch.mean(
                torch.sum(
                    bend_probability
                    * torch.log(bend_probability.clamp_min(EPS)),
                    dim=-1,
                )
            )

            loss = (
                concentration_mse
                + lambda_mae * concentration_mae
                + lambda_width_center * width_center_loss
                + lambda_bend_complexity * bend_complexity
                + lambda_entropy * entropy
            )

            if (
                min_mean_flow > 0.0
                and flow is not None
            ):
                mean_flow = flow.mean()
                flow_penalty = (
                    F.relu(
                        torch.tensor(
                            min_mean_flow,
                            dtype=flow.dtype,
                            device=flow.device,
                        )
                        - mean_flow
                    )
                    / max(min_mean_flow, FLOW_EPS)
                ) ** 2
                loss = loss + 0.05 * flow_penalty

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [raw_width, bend_logits],
                max_norm=10.0,
            )
            optimizer.step()

            if log_every > 0 and (
                step == 0
                or (step + 1) % log_every == 0
                or step + 1 == steps
            ):
                print(
                    f"[{sample.name}] restart={restart_index + 1}/{restarts} "
                    f"step={step + 1}/{steps} "
                    f"loss={float(loss.item()):.8f} "
                    f"rmse={float(torch.sqrt(concentration_mse).item()):.6f}"
                )

        # 固定离散弯曲数
        hard_class = torch.argmax(bend_logits.detach(), dim=-1)
        hard_bends = bend_classes[hard_class].unsqueeze(0)

        # 弯曲数固定后，只精修宽度
        refine_optimizer = torch.optim.Adam(
            [raw_width],
            lr=learning_rate * 0.35,
        )

        for _ in range(refine_steps):
            widths = decode_widths(
                raw_width,
                width_min,
                width_max,
            ).unsqueeze(0)

            prediction, flow = forward_predict(
                loaded=loaded,
                widths=widths,
                bend_values=hard_bends,
                inlet1=inlet1,
                inlet2=inlet2,
            )

            concentration_mse = F.mse_loss(prediction, target)
            concentration_mae = F.l1_loss(prediction, target)

            width_center = (width_min + width_max) / 2.0
            half_range = (width_max - width_min) / 2.0
            width_center_loss = torch.mean(
                ((widths - width_center) / max(half_range, EPS)) ** 2
            )

            refine_loss = (
                concentration_mse
                + lambda_mae * concentration_mae
                + lambda_width_center * width_center_loss
            )

            if (
                min_mean_flow > 0.0
                and flow is not None
            ):
                mean_flow = flow.mean()
                flow_penalty = (
                    F.relu(
                        torch.tensor(
                            min_mean_flow,
                            dtype=flow.dtype,
                            device=flow.device,
                        )
                        - mean_flow
                    )
                    / max(min_mean_flow, FLOW_EPS)
                ) ** 2
                refine_loss = refine_loss + 0.05 * flow_penalty

            refine_optimizer.zero_grad(set_to_none=True)
            refine_loss.backward()
            torch.nn.utils.clip_grad_norm_([raw_width], max_norm=10.0)
            refine_optimizer.step()

        with torch.no_grad():
            final_widths = decode_widths(
                raw_width,
                width_min,
                width_max,
            ).unsqueeze(0)

            final_prediction, final_flow = forward_predict(
                loaded=loaded,
                widths=final_widths,
                bend_values=hard_bends,
                inlet1=inlet1,
                inlet2=inlet2,
            )

            widths_np = final_widths[0].cpu().numpy()
            bends_np = hard_bends[0].round().to(torch.int64).cpu().numpy()
            distances_np = 1.0 + 6.0 * bends_np
            predicted_np = final_prediction[0].cpu().numpy()
            flow_np = (
                final_flow[0].cpu().numpy()
                if final_flow is not None
                else None
            )

        mae, rmse, maxae, spearman = compute_metrics(
            sample.concentration,
            predicted_np,
        )

        canonical_cost = (
            lambda_width_center
            * float(
                np.mean(
                    (
                        (
                            widths_np
                            - (width_min + width_max) / 2.0
                        )
                        / max((width_max - width_min) / 2.0, EPS)
                    ) ** 2
                )
            )
            + lambda_bend_complexity
            * float(np.mean((bends_np - 1.0) / 5.0))
        )

        objective = (
            rmse ** 2
            + lambda_mae * mae
            + canonical_cost
        )

        screening_pass = bool(
            mae <= screening_mae
            and rmse <= screening_rmse
            and maxae <= screening_maxae
            and spearman >= screening_spearman
        )

        candidate = DesignResult(
            sample_name=sample.name,
            inlet1=inlet1,
            inlet2=inlet2,
            target=sample.concentration.copy(),
            predicted=predicted_np.copy(),
            flow=None if flow_np is None else flow_np.copy(),
            widths=widths_np.copy(),
            bends=bends_np.copy(),
            distances=distances_np.copy(),
            mae=mae,
            rmse=rmse,
            maxae=maxae,
            spearman=spearman,
            screening_pass=screening_pass,
            restart_index=restart_index,
            objective=objective,
        )

        if best is None or (
            candidate.objective,
            candidate.rmse,
            candidate.maxae,
            candidate.restart_index,
        ) < (
            best.objective,
            best.rmse,
            best.maxae,
            best.restart_index,
        ):
            best = candidate

    if best is None:
        raise RuntimeError(f"{sample.name} 没有产生有效反向设计结果。")

    return best


# =============================================================================
# 6. 输出第二种结构表
# =============================================================================

def structure_table_headers(results: Sequence[DesignResult]) -> List[str]:
    """
    表头必须统一。若输入有多组目标，而每组弯曲组合不同，
    使用通用P1~P12表头；具体弯曲数保存在距离列和验证表中。
    单目标时使用“2to4”这类动态结构名称。
    """
    dynamic = len(results) == 1

    headers: List[str] = ["# ", "inlet1", "inlet2"]

    for chip_index in range(CHIP_COUNT):
        left_p = 2 * chip_index + 1
        right_p = left_p + 1

        if dynamic:
            left_bend = int(results[0].bends[chip_index, 0])
            right_bend = int(results[0].bends[chip_index, 1])
            structure_name = f"{left_bend}to{right_bend}"
        else:
            structure_name = f"chip{chip_index + 1}"

        headers.extend(
            [
                f"P{left_p} - {structure_name} 1 [mm]",
                "弯曲直道距离 [mm]",
                "位置",
                f"P{right_p} - {structure_name} 2 [mm]",
                "弯曲直道距离 [mm]",
                "位置",
            ]
        )

    return headers


def write_structure_table(
    path: Path,
    results: Sequence[DesignResult],
    width_decimals: int,
) -> None:
    headers = structure_table_headers(results)

    description_row: List[Any] = ["名称", np.nan, np.nan]
    for p_index in range(1, CHIP_COUNT * 2 + 1):
        description_row.extend([f"P{p_index}", np.nan, np.nan])

    rows: List[List[Any]] = [description_row]

    for sample_index, result in enumerate(results):
        row: List[Any] = [
            f"DP {sample_index}",
            float(result.inlet1),
            float(result.inlet2),
        ]

        for chip_index in range(CHIP_COUNT):
            left_width = round(
                float(result.widths[chip_index, 0]),
                width_decimals,
            )
            right_width = round(
                float(result.widths[chip_index, 1]),
                width_decimals,
            )
            left_distance = float(result.distances[chip_index, 0])
            right_distance = float(result.distances[chip_index, 1])
            position = float(chip_index + 1)

            row.extend(
                [
                    left_width,
                    left_distance,
                    position,
                    right_width,
                    right_distance,
                    position,
                ]
            )

        rows.append(row)

    frame = pd.DataFrame(rows, columns=headers)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_verification_table(
    path: Path,
    results: Sequence[DesignResult],
) -> None:
    rows: List[Dict[str, Any]] = []

    for result in results:
        row: Dict[str, Any] = {
            "target_name": result.sample_name,
            "inlet1": result.inlet1,
            "inlet2": result.inlet2,
            "MAE": result.mae,
            "RMSE": result.rmse,
            "MaxAE": result.maxae,
            "Spearman": result.spearman,
            "internal_screening_pass": result.screening_pass,
            "selected_restart": result.restart_index,
            "objective": result.objective,
        }

        for index in range(CHIP_COUNT):
            number = index + 1
            row[f"target_y{number}"] = float(result.target[index])
            row[f"predicted_y{number}"] = float(result.predicted[index])
            row[f"abs_error_y{number}"] = float(
                abs(result.predicted[index] - result.target[index])
            )

            row[f"left_width_chip{number}_mm"] = float(
                result.widths[index, 0]
            )
            row[f"right_width_chip{number}_mm"] = float(
                result.widths[index, 1]
            )
            row[f"left_bend_chip{number}"] = int(
                result.bends[index, 0]
            )
            row[f"right_bend_chip{number}"] = int(
                result.bends[index, 1]
            )
            row[f"left_distance_chip{number}_mm"] = float(
                result.distances[index, 0]
            )
            row[f"right_distance_chip{number}_mm"] = float(
                result.distances[index, 1]
            )

            if result.flow is not None:
                row[f"predicted_flow_y{number}"] = float(
                    result.flow[index]
                )

        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )


# =============================================================================
# 7. 命令行
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "输入含 inlet1、inlet2、y1~y6 的目标表，"
            "利用冻结Physics-GNN输出唯一芯片结构CSV。"
        )
    )

    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET_FILE,
        help=(
            "目标浓度CSV/XLSX。默认读取："
            "反向预测/反向预测输入/反向预测输入.csv"
        ),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_BUNDLED_CHECKPOINT,
        help=(
            "默认使用 Experiment D（seed 44）的 "
            "best_concentration_checkpoint.pt；"
            "也可通过 --checkpoint 手动覆盖。"
        ),
    )
    parser.add_argument(
        "--search-root",
        type=Path,
        default=None,
        help=(
            "额外指定检查点搜索目录。默认先搜索"
            "正向预测与反向预测/正向预测，再搜索整个项目根目录。"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="默认保存到：反向预测/反向预测输出/",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=1200)
    parser.add_argument("--refine-steps", type=int, default=300)
    parser.add_argument("--restarts", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.025)
    parser.add_argument("--temperature-start", type=float, default=2.0)
    parser.add_argument("--temperature-end", type=float, default=0.15)

    parser.add_argument(
        "--width-min",
        type=float,
        default=DEFAULT_WIDTH_MIN_MM,
    )
    parser.add_argument(
        "--width-max",
        type=float,
        default=DEFAULT_WIDTH_MAX_MM,
    )
    parser.add_argument("--width-decimals", type=int, default=3)

    parser.add_argument("--lambda-mae", type=float, default=0.10)
    parser.add_argument(
        "--lambda-width-center",
        type=float,
        default=0.0005,
        help="唯一结构规则：轻微偏好位于制造区间中部的宽度。",
    )
    parser.add_argument(
        "--lambda-bend-complexity",
        type=float,
        default=0.0003,
        help="唯一结构规则：浓度误差相近时轻微偏好较少弯曲。",
    )
    parser.add_argument(
        "--lambda-entropy",
        type=float,
        default=0.0005,
        help="促使弯曲数概率变为单一类别。",
    )
    parser.add_argument(
        "--min-mean-flow",
        type=float,
        default=0.0,
        help="仅A6双任务模型可用；0表示不设置最低平均出口流量。",
    )

    parser.add_argument("--screening-mae", type=float, default=0.02)
    parser.add_argument("--screening-rmse", type=float, default=0.03)
    parser.add_argument("--screening-maxae", type=float, default=0.05)
    parser.add_argument(
        "--screening-spearman",
        type=float,
        default=0.95,
    )

    parser.add_argument(
        "--target-recommended-min",
        type=float,
        default=0.10,
    )
    parser.add_argument(
        "--target-recommended-max",
        type=float,
        default=0.95,
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=200,
        help="每多少步打印一次；0表示不打印中间过程。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查目标表格式，不加载模型和优化。",
    )

    return parser


def resolve_device(text: str) -> torch.device:
    if text == "cpu":
        return torch.device("cpu")
    if text == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("指定了CUDA，但当前环境不可用。")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def resolve_cli_path(
    value: Path,
    *,
    base_dir: Path,
) -> Path:
    """
    绝对路径直接使用；相对路径优先相对于脚本所在目录解释。

    这样无论从PyCharm、终端还是项目根目录启动，路径行为都一致。
    """
    value = value.expanduser()
    if value.is_absolute():
        return value.resolve()
    return (base_dir / value).resolve()


def print_project_paths(
    *,
    target_path: Path,
    output_dir: Path,
    search_roots: Sequence[Path],
) -> None:
    print("项目路径识别：")
    print(f"  脚本目录：{INVERSE_PREDICTION_DIR}")
    print(f"  项目根目录：{PROJECT_ROOT}")
    print(f"  默认正向预测目录：{DEFAULT_FORWARD_PREDICTION_DIR}")
    print(f"  输入文件：{target_path}")
    print(f"  输出目录：{output_dir}")
    print("  检查点搜索目录：")
    for root in search_roots:
        print(f"    - {root}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.width_min <= 0.0:
        raise ValueError("--width-min 必须大于0。")
    if args.width_max <= args.width_min:
        raise ValueError("--width-max 必须大于 --width-min。")
    if args.steps < 1 or args.refine_steps < 0:
        raise ValueError("优化步数无效。")
    if args.restarts < 1:
        raise ValueError("--restarts 必须至少为1。")

    target_path = resolve_cli_path(
        args.target,
        base_dir=INVERSE_PREDICTION_DIR,
    )
    output_dir = resolve_cli_path(
        args.output_dir,
        base_dir=INVERSE_PREDICTION_DIR,
    )

    explicit_search_root = (
        resolve_cli_path(
            args.search_root,
            base_dir=PROJECT_ROOT,
        )
        if args.search_root is not None
        else None
    )
    search_roots = checkpoint_search_roots(explicit_search_root)

    print_project_paths(
        target_path=target_path,
        output_dir=output_dir,
        search_roots=search_roots,
    )

    targets = read_target_table(target_path)

    print(f"\n已读取目标数量：{len(targets)}")
    for sample in targets:
        print(
            f"  {sample.name}: inlet1={sample.inlet1:.6f}, "
            f"inlet2={sample.inlet2:.6f}, targets="
            + ", ".join(f"{value:.6f}" for value in sample.concentration)
        )

        if (
            float(sample.concentration.min())
            < args.target_recommended_min
            or float(sample.concentration.max())
            > args.target_recommended_max
        ):
            warnings.warn(
                f"{sample.name} 含有超出推荐训练密集范围 "
                f"[{args.target_recommended_min}, "
                f"{args.target_recommended_max}] 的目标浓度；"
                "程序仍会运行，但可能属于外推。",
                RuntimeWarning,
            )

    if args.dry_run:
        print("dry-run通过：输入表格式正确。")
        return

    set_seed(args.seed)
    device = resolve_device(args.device)

    checkpoint_path = (
        resolve_cli_path(
            args.checkpoint,
            base_dir=PROJECT_ROOT,
        )
        if args.checkpoint is not None
        else find_best_checkpoint(search_roots)
    )

    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"检查点不存在：{checkpoint_path}")

    print(f"设备：{device}")
    print(f"正向检查点：{checkpoint_path}")

    loaded = load_forward_model(
        checkpoint_path=checkpoint_path,
        device=device,
    )

    print(f"模型类型：{loaded.model_type}")

    results: List[DesignResult] = []

    for sample_index, sample in enumerate(targets):
        result = optimize_one_target(
            sample=sample,
            loaded=loaded,
            device=device,
            width_min=args.width_min,
            width_max=args.width_max,
            steps=args.steps,
            refine_steps=args.refine_steps,
            learning_rate=args.learning_rate,
            restarts=args.restarts,
            seed=args.seed + sample_index * 100_003,
            temperature_start=args.temperature_start,
            temperature_end=args.temperature_end,
            lambda_mae=args.lambda_mae,
            lambda_width_center=args.lambda_width_center,
            lambda_bend_complexity=args.lambda_bend_complexity,
            lambda_entropy=args.lambda_entropy,
            min_mean_flow=args.min_mean_flow,
            screening_mae=args.screening_mae,
            screening_rmse=args.screening_rmse,
            screening_maxae=args.screening_maxae,
            screening_spearman=args.screening_spearman,
            log_every=args.log_every,
        )
        results.append(result)

        print(
            f"\n{sample.name} 完成："
            f"inlet1={result.inlet1:.6f}, inlet2={result.inlet2:.6f}, "
            f"MAE={result.mae:.6f}, "
            f"RMSE={result.rmse:.6f}, "
            f"MaxAE={result.maxae:.6f}, "
            f"Spearman={result.spearman:.6f}, "
            f"内部筛选={'PASS' if result.screening_pass else 'FAIL'}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    structure_path = output_dir / "inverse_designed_structure.csv"
    verification_path = output_dir / "inverse_design_verification.csv"
    run_info_path = output_dir / "inverse_design_run_info.json"

    write_structure_table(
        structure_path,
        results,
        width_decimals=args.width_decimals,
    )
    write_verification_table(
        verification_path,
        results,
    )

    run_info: Dict[str, Any] = {
        "script": Path(__file__).name,
        "algorithm": "deterministic_tandem_inverse_optimization",
        "target_file": str(target_path),
        "script_file": str(SCRIPT_FILE),
        "inverse_prediction_dir": str(INVERSE_PREDICTION_DIR),
        "forward_prediction_dir": str(DEFAULT_FORWARD_PREDICTION_DIR),
        "project_root": str(PROJECT_ROOT),
        "checkpoint_search_roots": [
            str(root) for root in search_roots
        ],
        "target_count": len(targets),
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "forward_model_type": loaded.model_type,
        "device": str(device),
        "seed": args.seed,
        "width_constraint_mm": [
            args.width_min,
            args.width_max,
        ],
        "bend_classes": list(DEFAULT_BEND_VALUES),
        "distance_values_mm": list(DEFAULT_DISTANCE_VALUES_MM),
        "inlet_concentrations_source": "target_file_per_row",
        "target_inlet_pairs": [
            {
                "sample_name": sample.name,
                "inlet1": sample.inlet1,
                "inlet2": sample.inlet2,
            }
            for sample in targets
        ],
        "optimization": {
            "steps": args.steps,
            "refine_steps": args.refine_steps,
            "restarts": args.restarts,
            "learning_rate": args.learning_rate,
            "temperature_start": args.temperature_start,
            "temperature_end": args.temperature_end,
            "lambda_mae": args.lambda_mae,
            "lambda_width_center": args.lambda_width_center,
            "lambda_bend_complexity": args.lambda_bend_complexity,
            "lambda_entropy": args.lambda_entropy,
            "min_mean_flow": args.min_mean_flow,
        },
        "internal_screening": {
            "mae_max": args.screening_mae,
            "rmse_max": args.screening_rmse,
            "maxae_max": args.screening_maxae,
            "spearman_min": args.screening_spearman,
        },
        "results": [
            {
                "sample_name": result.sample_name,
                "inlet1": result.inlet1,
                "inlet2": result.inlet2,
                "mae": result.mae,
                "rmse": result.rmse,
                "maxae": result.maxae,
                "spearman": result.spearman,
                "internal_screening_pass": result.screening_pass,
                "selected_restart": result.restart_index,
            }
            for result in results
        ],
        "outputs": {
            "structure_csv": str(structure_path),
            "verification_csv": str(verification_path),
        },
        "important_note": (
            "内部筛选仅表示结构经过同一个Physics-GNN代理模型后接近目标；"
            "最终设计成功仍应使用Fluent/CFD重新验证。"
        ),
    }
    write_json(run_info_path, run_info)

    print("\n输出完成：")
    print(f"  结构表：{structure_path}")
    print(f"  正向复核：{verification_path}")
    print(f"  运行信息：{run_info_path}")


if __name__ == "__main__":
    main()
