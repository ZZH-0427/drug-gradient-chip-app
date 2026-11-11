# -*- coding: utf-8 -*-
from __future__ import annotations

"""
forward_predict_physics_gnn_experiment_D.py

Physics-GNN 实验D双任务微流控正向预测程序。

物理顺序
--------
表格从左到右 = 图片从上到下：

    P1  + P2  -> chip1 -> y1（最上方）
    P3  + P4  -> chip2 -> y2
    P5  + P6  -> chip3 -> y3
    P7  + P8  -> chip4 -> y4
    P9  + P10 -> chip5 -> y5
    P11 + P12 -> chip6 -> y6（最下方）

节点
----
    node 0 = inlet1
    node 1 = inlet2
    node 2~7 = chip1~chip6

边
--
每个完整芯片与两个入口双向连接：

    inlet1 <-> chip_i：使用奇数 P 的宽度与距离
    inlet2 <-> chip_i：使用偶数 P 的宽度与距离

共 24 条有向边，每条边 9 维物理特征。

默认检查点
----------
GNN/Physics-GNN/model/experiment_D_balanced_medium_weight/seed_44/best_concentration_checkpoint.pt

默认输入
--------
正向预测与反向预测/正向预测输入/正向预测结构.csv

默认输出
--------
正向预测与反向预测/正向预测结果/
    physics_gnn_forward_prediction_results.csv
    physics_gnn_forward_prediction_graph_audit.csv
    physics_gnn_forward_prediction_run_info.json

重要说明
--------
1. 本程序加载 PhysicsGuidedDualTaskGNN 双任务检查点；
2. 标准化参数直接读取训练检查点，不会用预测表重新拟合；
3. P13~P20 不作为正向预测输入；模型同时输出六出口浓度和六出口质量流量；
4. 不复用训练数据第一张图的 edge_attr，而是根据每条预测结构重新构建；
5. 默认不裁剪模型输出，超出 [0,1] 时会明确标记；
6. 支持 CSV、XLSX、XLS；
7. 支持 --dry-run，只检查输入和构图，不加载模型；
8. inlet2 为高浓度时，在输入表中保持列顺序不变，填写 inlet1=0、inlet2=1。

命令行示例
----------
python forward_predict_physics_gnn_experiment_D.py

python forward_predict_physics_gnn_experiment_D.py ^
    --input "正向预测结构.csv" ^
    --checkpoint "best_concentration_checkpoint.pt" ^
    --output-dir "正向预测结果"

python forward_predict_physics_gnn_experiment_D.py ^
    --input "正向预测结构.csv" ^
    --dry-run
"""

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import Tensor, nn

try:
    from torch_geometric.data import Batch, Data
    from torch_geometric.nn import TransformerConv, global_mean_pool
except ImportError:
    # 允许在没有 PyTorch Geometric 的环境中使用 --dry-run 检查表格与构图。
    Batch = None
    Data = None
    TransformerConv = None
    global_mean_pool = None


# =============================================================================
# 0. 配置
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent

INPUT_DIR = SCRIPT_DIR / "正向预测输入"
OUTPUT_DIR = SCRIPT_DIR / "正向预测结果"

PREFERRED_INPUT_FILE = INPUT_DIR / "正向预测结构.csv"
CHECKPOINT_NAME = "best_concentration_checkpoint.pt"

RESULT_FILENAME = "physics_gnn_forward_prediction_results.csv"
GRAPH_AUDIT_FILENAME = "physics_gnn_forward_prediction_graph_audit.csv"
RUN_INFO_FILENAME = "physics_gnn_forward_prediction_run_info.json"

EXPECTED_NODE_COUNT = 8
EXPECTED_CHIP_COUNT = 6
EXPECTED_NODE_FEATURE_DIM = 15
EXPECTED_EDGE_COUNT = 24
EXPECTED_EDGE_FEATURE_DIM = 9
EXPECTED_GLOBAL_FEATURE_DIM = 2
EXPECTED_OUTPUT_DIM = 6
EXPECTED_CHIP_PHYSICS_DIM = 7
FLOW_EPS = 1.0e-18

INLET1_NODE_INDEX = 0
INLET2_NODE_INDEX = 1
CHIP_NODE_START_INDEX = 2

BOUNDARY_MIN = 0.0
BOUNDARY_MAX = 1.0

# 默认保留模型原始输出。
CLIP_PREDICTION_TO_01 = False

# 输入分布提示阈值，仅用于警告，不阻止预测。
Z_WARNING_THRESHOLD = 3.0
Z_SEVERE_THRESHOLD = 5.0


NODE_FEATURE_NAMES: Tuple[str, ...] = (
    "node_type_inlet1",
    "node_type_inlet2",
    "node_type_chip",
    "boundary_concentration",
    "left_width_mm",
    "right_width_mm",
    "left_bend_straight_distance_mm",
    "right_bend_straight_distance_mm",
    "left_position",
    "right_position",
    "assembly_position_norm",
    "chip_start_norm",
    "chip_end_norm",
    "chip_signed_span_norm",
    "chip_absolute_span_norm",
)

EDGE_FEATURE_NAMES: Tuple[str, ...] = (
    "channel_width_mm",
    "bend_straight_distance_mm",
    "assembly_position_norm",
    "chip_signed_span_norm",
    "chip_absolute_span_norm",
    "side_is_inlet1",
    "side_is_inlet2",
    "direction_to_chip",
    "direction_from_chip",
)

CHIP_PHYSICS_FEATURE_NAMES: Tuple[str, ...] = (
    "log_width_ratio_left_over_right",
    "normalized_width_difference",
    "geometric_mean_width",
    "width_sum",
    "log_distance_ratio_right_over_left",
    "normalized_distance_difference",
    "geometric_mean_distance",
)

DEFAULT_TARGET_NAMES: Tuple[str, ...] = (
    "y1",
    "y2",
    "y3",
    "y4",
    "y5",
    "y6",
)


# =============================================================================
# 1. 数据结构
# =============================================================================

@dataclass(frozen=True)
class InputChip:
    chip_name: str
    left_width_mm: float
    right_width_mm: float
    left_distance_mm: float
    right_distance_mm: float
    left_position: float
    right_position: float


@dataclass(frozen=True)
class InputSample:
    sample_name: str
    inlet1: float
    inlet2: float
    chips: Tuple[InputChip, ...]


@dataclass
class LoadedPhysicsModel:
    model: nn.Module
    checkpoint: Dict[str, Any]
    normalizers: Dict[str, Tensor]
    checkpoint_path: Path
    model_type: str


# =============================================================================
# 2. 模型：与 Physics-GNN 实验D双任务训练结构严格一致
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

        if TransformerConv is None:
            raise ImportError(
                "正式 Physics-GNN 预测需要安装 torch_geometric。"
            )

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
            raise RuntimeError("每张图必须固定8个节点。")

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

        physics_for_nodes[:, CHIP_NODE_START_INDEX:, :] = chip_physics_z

        node_input = torch.cat(
            [node_x, physics_for_nodes],
            dim=2,
        ).reshape(
            graph_count * EXPECTED_NODE_COUNT,
            -1,
        )

        hidden = F.gelu(self.input_projection(node_input))

        for conv, norm in zip(self.convs, self.norms):
            residual = hidden

            if self.use_edge_attr:
                message = conv(
                    hidden,
                    data.edge_index,
                    data.edge_attr,
                )
            else:
                message = conv(hidden, data.edge_index)

            message = self.dropout(F.gelu(norm(message)))
            hidden = residual + message

        node_hidden = hidden.reshape(
            graph_count,
            EXPECTED_NODE_COUNT,
            self.hidden_channels,
        )

        chip_hidden = node_hidden[:, CHIP_NODE_START_INDEX:, :]

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

        width_weight = F.softplus(self.raw_width_ratio_weight)
        distance_weight = F.softplus(self.raw_distance_ratio_weight)

        local_logit = (
            self.local_concentration_bias
            + width_weight * chip_physics_raw[:, :, 0]
            + distance_weight * chip_physics_raw[:, :, 4]
        )

        correction = (
            self.concentration_correction_head(context)
            .squeeze(-1)
        )

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


# =============================================================================
# 3. 通用工具
# =============================================================================

def safe_torch_load(path: Path) -> Any:
    try:
        return torch.load(
            path,
            map_location="cpu",
            weights_only=False,
        )
    except TypeError:
        return torch.load(
            path,
            map_location="cpu",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and math.isnan(value):
        return ""

    return str(value).strip()


def normalized_name(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("毫米", "mm")
    return re.sub(
        r"[^0-9a-z\u4e00-\u9fff]+",
        "",
        text,
    )


def as_float(
    value: Any,
    display_name: str,
) -> float:
    text = clean_text(value).replace(",", "")

    if not text:
        raise ValueError(f"{display_name} 为空。")

    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(
            f"{display_name} 不是有效数字：{value!r}"
        ) from exc

    if not math.isfinite(number):
        raise ValueError(
            f"{display_name} 不是有限数值：{value!r}"
        )

    return number


def write_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            dict(payload),
            handle,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
            default=str,
        )


def find_project_root(start_dir: Path) -> Path:
    for candidate in (
        start_dir,
        *start_dir.parents,
    ):
        if (
            candidate
            / "GNN"
            / "Physics-GNN"
        ).is_dir():
            return candidate.resolve()

    raise FileNotFoundError(
        "无法定位项目根目录。\n"
        "推荐把脚本放在：\n"
        "pytorch_geometric-master/正向预测与反向预测/"
    )


def checkpoint_candidates(
    project_root: Optional[Path],
) -> List[Path]:
    result = [
        SCRIPT_DIR / CHECKPOINT_NAME,
    ]

    if project_root is not None:
        result.extend([
            (
                project_root
                / "GNN"
                / "Physics-GNN"
                / "model"
                / "experiment_D_balanced_medium_weight"
                / "seed_44"
                / CHECKPOINT_NAME
            ),
        ])

    return result


def find_checkpoint(
    explicit_path: Optional[Path],
    project_root: Optional[Path],
) -> Path:
    if explicit_path is not None:
        explicit_path = explicit_path.expanduser().resolve()
        if not explicit_path.is_file():
            raise FileNotFoundError(
                f"指定检查点不存在：{explicit_path}"
            )
        return explicit_path

    candidates = checkpoint_candidates(project_root)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    searched = "\n".join(
        f"  - {candidate}"
        for candidate in candidates
    )

    raise FileNotFoundError(
        "没有找到 Physics-GNN 实验D双任务检查点。\n"
        f"已经检查：\n{searched}\n"
        "也可使用 --checkpoint 显式指定。"
    )


def dataset_candidates(
    project_root: Optional[Path],
) -> List[Path]:
    if project_root is None:
        return []

    return [
        (
            project_root
            / "GNN"
            / "Physics-GNN"
            / "数据集"
            / "physics_gnn_dataset.pt"
        ),
        (
            project_root
            / "GNN"
            / "Physics-GNN"
            / "physics_gnn_dataset.pt"
        ),
    ]


def find_optional_dataset(
    project_root: Optional[Path],
) -> Optional[Path]:
    for candidate in dataset_candidates(
        project_root
    ):
        if candidate.is_file():
            return candidate.resolve()

    return None


def find_input_file(
    explicit_path: Optional[Path],
) -> Path:
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise FileNotFoundError(
                f"指定输入表不存在：{explicit_path}"
            )
        return explicit_path.resolve()

    INPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if PREFERRED_INPUT_FILE.is_file():
        return PREFERRED_INPUT_FILE.resolve()

    candidates: List[Path] = []

    for directory in (
        INPUT_DIR,
        SCRIPT_DIR,
    ):
        for pattern in (
            "*.csv",
            "*.xlsx",
            "*.xls",
        ):
            candidates.extend(
                directory.glob(pattern)
            )

    candidates = sorted(
        {
            path.resolve()
            for path in candidates
            if not path.name.startswith("~$")
            and "result" not in path.name.lower()
            and "audit" not in path.name.lower()
        },
        key=lambda item: str(item).lower(),
    )

    if not candidates:
        raise FileNotFoundError(
            "没有找到正向预测输入表。\n"
            f"请放入：{INPUT_DIR}"
        )

    if len(candidates) > 1:
        print(
            "[提示] 找到多个输入表，本次读取：",
            candidates[0],
        )

    return candidates[0]


def read_table_without_header(
    path: Path,
) -> pd.DataFrame:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        last_error: Optional[Exception] = None

        for encoding in (
            "utf-8-sig",
            "utf-8",
            "gbk",
        ):
            try:
                return pd.read_csv(
                    path,
                    header=None,
                    dtype=object,
                    encoding=encoding,
                    keep_default_na=False,
                )
            except UnicodeDecodeError as exc:
                last_error = exc

        assert last_error is not None
        raise last_error

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(
            path,
            header=None,
            dtype=object,
            keep_default_na=False,
        )

    raise ValueError(
        f"不支持的输入格式：{path.suffix}"
    )


# =============================================================================
# 4. 输入表解析
# =============================================================================

P_COLUMN_PATTERN = re.compile(
    r"^\s*p\s*(1[0-2]|[1-9])(?:\D|$)",
    flags=re.IGNORECASE,
)

# 只识别真正的芯片名，不把 “P1 - 5” 错读成 1to5。
CHANNEL_PATTERN = re.compile(
    r"(\d+)\s*(?:to|→|至)\s*(\d+)",
    flags=re.IGNORECASE,
)


def is_distance_header(value: Any) -> bool:
    name = normalized_name(value)

    return (
        "距离" in name
        or "distance" in name
        or "length" in name
        or "path" in name
    )


def is_position_header(value: Any) -> bool:
    name = normalized_name(value)

    return (
        "位置" in name
        or "position" in name
    )


def parse_channel_name(value: Any) -> str:
    match = CHANNEL_PATTERN.search(
        clean_text(value)
    )

    if match is None:
        return ""

    return (
        f"{int(match.group(1))}"
        f"to"
        f"{int(match.group(2))}"
    )


def locate_columns(
    headers: Sequence[Any],
) -> Dict[str, Any]:
    inlet1_index: Optional[int] = None
    inlet2_index: Optional[int] = None
    p_width_columns: Dict[int, int] = {}

    for index, header in enumerate(headers):
        name = normalized_name(header)

        if name in {
            "inlet1",
            "inlet1concentration",
            "入口1",
            "入口1浓度",
        }:
            inlet1_index = index

        if name in {
            "inlet2",
            "inlet2concentration",
            "入口2",
            "入口2浓度",
        }:
            inlet2_index = index

        match = P_COLUMN_PATTERN.match(
            clean_text(header)
        )

        if match:
            p_width_columns[
                int(match.group(1))
            ] = index

    if inlet1_index is None or inlet2_index is None:
        raise ValueError(
            "输入表必须包含 inlet1 和 inlet2 两列。"
        )

    missing_p = [
        number
        for number in range(1, 13)
        if number not in p_width_columns
    ]

    if missing_p:
        raise ValueError(
            "输入表缺少："
            + ", ".join(
                f"P{number}"
                for number in missing_p
            )
        )

    ordered_columns = sorted(
        p_width_columns.items(),
        key=lambda item: item[1],
    )

    p_columns: Dict[int, Dict[str, Any]] = {}

    for order_index, (
        p_number,
        width_index,
    ) in enumerate(ordered_columns):
        if order_index + 1 < len(ordered_columns):
            stop_index = ordered_columns[
                order_index + 1
            ][1]
        else:
            stop_index = len(headers)

        distance_index: Optional[int] = None
        position_index: Optional[int] = None

        for index in range(
            width_index + 1,
            stop_index,
        ):
            if (
                distance_index is None
                and is_distance_header(
                    headers[index]
                )
            ):
                distance_index = index

            if (
                position_index is None
                and is_position_header(
                    headers[index]
                )
            ):
                position_index = index

        # 兼容标准表中连续三列：宽度、距离、位置。
        if distance_index is None:
            candidate = width_index + 1
            if candidate < len(headers):
                distance_index = candidate

        if position_index is None:
            candidate = width_index + 2
            if candidate < len(headers):
                position_index = candidate

        if distance_index is None or position_index is None:
            raise ValueError(
                f"P{p_number} 后没有找到距离列和位置列。"
            )

        chip_name = parse_channel_name(
            headers[width_index]
        )

        if not chip_name:
            raise ValueError(
                f"P{p_number} 列标题没有识别到芯片名称，"
                "例如 5to4。"
            )

        p_columns[p_number] = {
            "width": width_index,
            "distance": distance_index,
            "position": position_index,
            "chip_name": chip_name,
        }

    return {
        "sample_name": 0,
        "inlet1": inlet1_index,
        "inlet2": inlet2_index,
        "p": p_columns,
    }


def row_is_description(
    row: Sequence[Any],
) -> bool:
    first = normalized_name(
        row[0] if row else ""
    )

    if first in {
        "名称",
        "name",
        "样本",
        "samplename",
    }:
        return True

    tokens = {
        normalized_name(value)
        for value in row
        if clean_text(value)
    }

    return (
        "p1" in tokens
        and "p12" in tokens
    )


def parse_input_samples(path: Path) -> List[InputSample]:
    dataframe = read_table_without_header(path)

    if dataframe.empty or len(dataframe.index) < 2:
        raise RuntimeError("输入表没有有效数据。")

    headers = dataframe.iloc[0].tolist()
    columns = locate_columns(headers)

    samples: List[InputSample] = []

    for row_index in range(
        1,
        len(dataframe.index),
    ):
        row = dataframe.iloc[row_index].tolist()

        if not any(
            clean_text(value)
            for value in row
        ):
            continue

        if row_is_description(row):
            continue

        sample_name = (
            clean_text(
                row[columns["sample_name"]]
            )
            or f"sample_{row_index}"
        )

        inlet1 = as_float(
            row[columns["inlet1"]],
            f"{sample_name}.inlet1",
        )

        inlet2 = as_float(
            row[columns["inlet2"]],
            f"{sample_name}.inlet2",
        )

        if not (
            BOUNDARY_MIN <= inlet1 <= BOUNDARY_MAX
            and BOUNDARY_MIN <= inlet2 <= BOUNDARY_MAX
        ):
            raise ValueError(
                f"{sample_name} 的入口浓度应位于 [0,1]："
                f"inlet1={inlet1}, inlet2={inlet2}"
            )

        chips: List[InputChip] = []

        for chip_index in range(
            EXPECTED_CHIP_COUNT
        ):
            left_p = chip_index * 2 + 1
            right_p = left_p + 1

            left_columns = columns["p"][left_p]
            right_columns = columns["p"][right_p]

            left_chip_name = str(
                left_columns["chip_name"]
            )
            right_chip_name = str(
                right_columns["chip_name"]
            )

            if left_chip_name != right_chip_name:
                raise ValueError(
                    f"{sample_name} 的 P{left_p}/P{right_p} "
                    "不是同一个完整芯片："
                    f"{left_chip_name} vs {right_chip_name}"
                )

            expected_position = float(
                chip_index + 1
            )

            left_position = as_float(
                row[left_columns["position"]],
                f"{sample_name}.P{left_p}.位置",
            )

            right_position = as_float(
                row[right_columns["position"]],
                f"{sample_name}.P{right_p}.位置",
            )

            if abs(
                left_position - expected_position
            ) > 1e-6:
                raise ValueError(
                    f"{sample_name}.P{left_p} 位置应为 "
                    f"{expected_position:g}，实际为 "
                    f"{left_position:g}。"
                )

            if abs(
                right_position - expected_position
            ) > 1e-6:
                raise ValueError(
                    f"{sample_name}.P{right_p} 位置应为 "
                    f"{expected_position:g}，实际为 "
                    f"{right_position:g}。"
                )

            chip = InputChip(
                chip_name=left_chip_name,
                left_width_mm=as_float(
                    row[left_columns["width"]],
                    f"{sample_name}.P{left_p}.宽度",
                ),
                right_width_mm=as_float(
                    row[right_columns["width"]],
                    f"{sample_name}.P{right_p}.宽度",
                ),
                left_distance_mm=as_float(
                    row[left_columns["distance"]],
                    f"{sample_name}.P{left_p}.距离",
                ),
                right_distance_mm=as_float(
                    row[right_columns["distance"]],
                    f"{sample_name}.P{right_p}.距离",
                ),
                left_position=left_position,
                right_position=right_position,
            )

            if (
                chip.left_width_mm <= 0
                or chip.right_width_mm <= 0
                or chip.left_distance_mm < 0
                or chip.right_distance_mm < 0
            ):
                raise ValueError(
                    f"{sample_name} 的 chip{chip_index + 1} "
                    "存在非正宽度或负距离。"
                )

            chips.append(chip)

        samples.append(
            InputSample(
                sample_name=sample_name,
                inlet1=inlet1,
                inlet2=inlet2,
                chips=tuple(chips),
            )
        )

    if not samples:
        raise RuntimeError(
            "输入表中没有可预测的数据行。"
        )

    return samples


# =============================================================================
# 5. 图构建：严格复现训练数据
# =============================================================================

def parse_chip_structure(
    chip_name: str,
) -> Tuple[float, float, float, float]:
    match = CHANNEL_PATTERN.search(chip_name)

    if match is None:
        raise ValueError(
            f"无法解析芯片名称：{chip_name}"
        )

    start = float(match.group(1))
    end = float(match.group(2))

    if not (
        1.0 <= start <= 6.0
        and 1.0 <= end <= 6.0
    ):
        raise ValueError(
            f"芯片端点必须位于 1~6：{chip_name}"
        )

    signed_span = end - start

    return (
        start / 6.0,
        end / 6.0,
        signed_span / 5.0,
        abs(signed_span) / 5.0,
    )


def build_inlet_node_row(
    inlet_index: int,
    concentration: float,
) -> List[float]:
    if inlet_index == 1:
        node_type = [1.0, 0.0, 0.0]
    elif inlet_index == 2:
        node_type = [0.0, 1.0, 0.0]
    else:
        raise ValueError(
            "inlet_index 只能为 1 或 2。"
        )

    row = node_type + [
        float(concentration),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ]

    if len(row) != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError(
            "入口节点特征维度不是15。"
        )

    return row


def build_chip_node_row(
    chip: InputChip,
    chip_index: int,
) -> List[float]:
    (
        chip_start_norm,
        chip_end_norm,
        chip_signed_span_norm,
        chip_absolute_span_norm,
    ) = parse_chip_structure(
        chip.chip_name
    )

    assembly_position_norm = (
        float(chip_index)
        / float(EXPECTED_CHIP_COUNT - 1)
    )

    row = [
        0.0,
        0.0,
        1.0,
        0.0,
        float(chip.left_width_mm),
        float(chip.right_width_mm),
        float(chip.left_distance_mm),
        float(chip.right_distance_mm),
        float(chip.left_position),
        float(chip.right_position),
        assembly_position_norm,
        chip_start_norm,
        chip_end_norm,
        chip_signed_span_norm,
        chip_absolute_span_norm,
    ]

    if len(row) != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError(
            "芯片节点特征维度不是15。"
        )

    return row


def build_raw_x(sample: InputSample) -> Tensor:
    rows: List[List[float]] = [
        build_inlet_node_row(
            1,
            sample.inlet1,
        ),
        build_inlet_node_row(
            2,
            sample.inlet2,
        ),
    ]

    for chip_index, chip in enumerate(
        sample.chips
    ):
        rows.append(
            build_chip_node_row(
                chip,
                chip_index,
            )
        )

    x = torch.tensor(
        rows,
        dtype=torch.float32,
    )

    if tuple(x.shape) != (
        EXPECTED_NODE_COUNT,
        EXPECTED_NODE_FEATURE_DIM,
    ):
        raise RuntimeError(
            "x shape 应为 (8,15)，"
            f"实际为 {tuple(x.shape)}"
        )

    return x


def build_raw_edges(
    sample: InputSample,
) -> Tuple[Tensor, Tensor]:
    sources: List[int] = []
    targets: List[int] = []
    features: List[List[float]] = []

    def append_edge(
        *,
        source: int,
        target: int,
        width: float,
        distance: float,
        assembly_position_norm: float,
        chip_signed_span_norm: float,
        chip_absolute_span_norm: float,
        side_is_inlet1: float,
        side_is_inlet2: float,
        direction_to_chip: float,
        direction_from_chip: float,
    ) -> None:
        sources.append(source)
        targets.append(target)

        features.append([
            float(width),
            float(distance),
            float(assembly_position_norm),
            float(chip_signed_span_norm),
            float(chip_absolute_span_norm),
            float(side_is_inlet1),
            float(side_is_inlet2),
            float(direction_to_chip),
            float(direction_from_chip),
        ])

    for chip_index, chip in enumerate(
        sample.chips
    ):
        chip_node_index = (
            CHIP_NODE_START_INDEX
            + chip_index
        )

        assembly_position_norm = (
            float(chip_index)
            / float(EXPECTED_CHIP_COUNT - 1)
        )

        (
            _,
            _,
            chip_signed_span_norm,
            chip_absolute_span_norm,
        ) = parse_chip_structure(
            chip.chip_name
        )

        # 1. inlet1 -> chip：奇数 P。
        append_edge(
            source=INLET1_NODE_INDEX,
            target=chip_node_index,
            width=chip.left_width_mm,
            distance=chip.left_distance_mm,
            assembly_position_norm=assembly_position_norm,
            chip_signed_span_norm=chip_signed_span_norm,
            chip_absolute_span_norm=chip_absolute_span_norm,
            side_is_inlet1=1.0,
            side_is_inlet2=0.0,
            direction_to_chip=1.0,
            direction_from_chip=0.0,
        )

        # 2. inlet2 -> chip：偶数 P。
        append_edge(
            source=INLET2_NODE_INDEX,
            target=chip_node_index,
            width=chip.right_width_mm,
            distance=chip.right_distance_mm,
            assembly_position_norm=assembly_position_norm,
            chip_signed_span_norm=chip_signed_span_norm,
            chip_absolute_span_norm=chip_absolute_span_norm,
            side_is_inlet1=0.0,
            side_is_inlet2=1.0,
            direction_to_chip=1.0,
            direction_from_chip=0.0,
        )

        # 3. chip -> inlet1：奇数 P 的反向消息边。
        append_edge(
            source=chip_node_index,
            target=INLET1_NODE_INDEX,
            width=chip.left_width_mm,
            distance=chip.left_distance_mm,
            assembly_position_norm=assembly_position_norm,
            chip_signed_span_norm=chip_signed_span_norm,
            chip_absolute_span_norm=chip_absolute_span_norm,
            side_is_inlet1=1.0,
            side_is_inlet2=0.0,
            direction_to_chip=0.0,
            direction_from_chip=1.0,
        )

        # 4. chip -> inlet2：偶数 P 的反向消息边。
        append_edge(
            source=chip_node_index,
            target=INLET2_NODE_INDEX,
            width=chip.right_width_mm,
            distance=chip.right_distance_mm,
            assembly_position_norm=assembly_position_norm,
            chip_signed_span_norm=chip_signed_span_norm,
            chip_absolute_span_norm=chip_absolute_span_norm,
            side_is_inlet1=0.0,
            side_is_inlet2=1.0,
            direction_to_chip=0.0,
            direction_from_chip=1.0,
        )

    edge_index = torch.tensor(
        [sources, targets],
        dtype=torch.long,
    )

    edge_attr = torch.tensor(
        features,
        dtype=torch.float32,
    )

    if tuple(edge_index.shape) != (
        2,
        EXPECTED_EDGE_COUNT,
    ):
        raise RuntimeError(
            "edge_index shape 应为 (2,24)，"
            f"实际为 {tuple(edge_index.shape)}"
        )

    if tuple(edge_attr.shape) != (
        EXPECTED_EDGE_COUNT,
        EXPECTED_EDGE_FEATURE_DIM,
    ):
        raise RuntimeError(
            "edge_attr shape 应为 (24,9)，"
            f"实际为 {tuple(edge_attr.shape)}"
        )

    return edge_index, edge_attr


def build_raw_u(sample: InputSample) -> Tensor:
    u = torch.tensor(
        [[sample.inlet1, sample.inlet2]],
        dtype=torch.float32,
    )

    if tuple(u.shape) != (
        1,
        EXPECTED_GLOBAL_FEATURE_DIM,
    ):
        raise RuntimeError(
            "u shape 应为 (1,2)。"
        )

    return u



def build_raw_chip_physics(sample: InputSample) -> Tensor:
    """由六个芯片几何构造训练时使用的 chip_physics[6,7]。"""

    rows: List[List[float]] = []
    eps = 1.0e-12

    for chip_index, chip in enumerate(sample.chips, start=1):
        left_width = float(chip.left_width_mm)
        right_width = float(chip.right_width_mm)
        left_distance = float(chip.left_distance_mm)
        right_distance = float(chip.right_distance_mm)

        if min(
            left_width,
            right_width,
            left_distance,
            right_distance,
        ) <= 0.0:
            raise ValueError(
                f"{sample.sample_name} 的chip{chip_index}存在"
                "非正宽度或距离，无法计算物理比例。"
            )

        width_sum = left_width + right_width
        distance_sum = left_distance + right_distance

        rows.append([
            math.log((left_width + eps) / (right_width + eps)),
            (left_width - right_width) / (width_sum + eps),
            math.sqrt(left_width * right_width),
            width_sum,
            math.log((right_distance + eps) / (left_distance + eps)),
            (right_distance - left_distance) / (distance_sum + eps),
            math.sqrt(left_distance * right_distance),
        ])

    result = torch.tensor(rows, dtype=torch.float32)

    if tuple(result.shape) != (
        EXPECTED_CHIP_COUNT,
        EXPECTED_CHIP_PHYSICS_DIM,
    ):
        raise RuntimeError(
            "chip_physics shape应为(6,7)，"
            f"实际为{tuple(result.shape)}"
        )

    return result


# =============================================================================
# 6. 与本地训练数据结构交叉校验
# =============================================================================

def get_payload_graphs(
    payload: Any,
) -> Tuple[Dict[str, Any], List[Any]]:
    if isinstance(payload, Mapping):
        graphs = payload.get("graphs")

        if not isinstance(graphs, list):
            raise KeyError(
                "physics_gnn_dataset.pt 缺少 graphs 列表。"
            )

        return dict(payload), graphs

    if isinstance(payload, (list, tuple)):
        return {}, list(payload)

    raise TypeError(
        "不支持的数据集格式："
        f"{type(payload).__name__}"
    )


def name_list(
    payload: Mapping[str, Any],
    graph: Any,
    keys: Sequence[str],
) -> List[str]:
    for key in keys:
        value = payload.get(key)

        if value is None:
            value = getattr(graph, key, None)

        if value is None:
            continue

        if isinstance(value, str):
            result = [
                item.strip()
                for item in value.split(",")
                if item.strip()
            ]
        else:
            try:
                result = [
                    clean_text(item)
                    for item in list(value)
                ]
            except TypeError:
                continue

        if result:
            return result

    return []


def validate_against_training_dataset(
    dataset_path: Optional[Path],
    sample: InputSample,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "dataset_validation_performed": False,
        "dataset_path": (
            None
            if dataset_path is None
            else str(dataset_path)
        ),
    }

    if dataset_path is None:
        return result

    payload, graphs = get_payload_graphs(
        safe_torch_load(dataset_path)
    )

    if not graphs:
        raise RuntimeError(
            "训练数据集 graphs 为空。"
        )

    template = graphs[0]

    raw_x = build_raw_x(sample)
    raw_edge_index, raw_edge_attr = (
        build_raw_edges(sample)
    )
    raw_u = build_raw_u(sample)

    template_edge_index = (
        template.edge_index
        .detach()
        .cpu()
        .long()
    )

    if not torch.equal(
        raw_edge_index,
        template_edge_index,
    ):
        raise RuntimeError(
            "预测程序构造的 edge_index 顺序与训练数据不一致。\n"
            f"预测：\n{raw_edge_index}\n"
            f"训练模板：\n{template_edge_index}"
        )

    node_names = name_list(
        payload,
        template,
        (
            "node_feature_names",
            "x_feature_names",
            "feature_names",
        ),
    )

    edge_names = name_list(
        payload,
        template,
        (
            "edge_feature_names",
            "edge_attr_names",
            "physics_edge_feature_names",
        ),
    )

    if node_names and tuple(node_names) != NODE_FEATURE_NAMES:
        raise RuntimeError(
            "训练数据中的节点特征顺序与预测程序不一致。\n"
            f"训练：{node_names}\n"
            f"预测：{list(NODE_FEATURE_NAMES)}"
        )

    if edge_names and tuple(edge_names) != EDGE_FEATURE_NAMES:
        raise RuntimeError(
            "训练数据中的边特征顺序与预测程序不一致。\n"
            f"训练：{edge_names}\n"
            f"预测：{list(EDGE_FEATURE_NAMES)}"
        )

    if tuple(template.x.shape) != (
        EXPECTED_NODE_COUNT,
        EXPECTED_NODE_FEATURE_DIM,
    ):
        raise RuntimeError(
            "训练数据模板 x 不是 (8,15)。"
        )

    if tuple(template.edge_attr.shape) != (
        EXPECTED_EDGE_COUNT,
        EXPECTED_EDGE_FEATURE_DIM,
    ):
        raise RuntimeError(
            "训练数据模板 edge_attr 不是 (24,9)。"
        )

    if int(template.u.numel()) != EXPECTED_GLOBAL_FEATURE_DIM:
        raise RuntimeError(
            "训练数据模板 u 不是2维。"
        )

    template_chip_physics = getattr(template, "chip_physics", None)
    if not torch.is_tensor(template_chip_physics):
        raise RuntimeError(
            "训练数据模板缺少 chip_physics；"
            "请确认使用与实验D一致的 Physics-GNN 数据集。"
        )

    if tuple(template_chip_physics.shape) != (
        EXPECTED_CHIP_COUNT,
        EXPECTED_CHIP_PHYSICS_DIM,
    ):
        raise RuntimeError(
            "训练数据模板 chip_physics 不是 (6,7)。"
        )

    raw_chip_physics = build_raw_chip_physics(sample)

    result.update({
        "dataset_validation_performed": True,
        "dataset_graph_count": len(graphs),
        "node_feature_names": (
            node_names
            or list(NODE_FEATURE_NAMES)
        ),
        "edge_feature_names": (
            edge_names
            or list(EDGE_FEATURE_NAMES)
        ),
        "constructed_x_shape": list(
            raw_x.shape
        ),
        "constructed_edge_index_shape": list(
            raw_edge_index.shape
        ),
        "constructed_edge_attr_shape": list(
            raw_edge_attr.shape
        ),
        "constructed_u_shape": list(
            raw_u.shape
        ),
        "constructed_chip_physics_shape": list(
            raw_chip_physics.shape
        ),
        "edge_index_matches_training": True,
    })

    return result


# =============================================================================
# 7. 检查点加载
# =============================================================================

def normalize_tensor(
    value: Tensor,
    mean: Tensor,
    std: Tensor,
    display_name: str,
) -> Tensor:
    mean = mean.detach().cpu().float().reshape(-1)
    std = std.detach().cpu().float().reshape(-1)

    if value.shape[-1] != mean.numel():
        raise ValueError(
            f"{display_name}维度与检查点不一致："
            f"{value.shape[-1]} vs {mean.numel()}"
        )

    safe_std = torch.where(
        std.abs() < 1.0e-12,
        torch.ones_like(std),
        std,
    )

    return (value.float() - mean) / safe_std


def load_dualtask_model(
    checkpoint_path: Path,
    device: torch.device,
) -> LoadedPhysicsModel:
    checkpoint_raw = safe_torch_load(checkpoint_path)

    if not isinstance(checkpoint_raw, Mapping):
        raise TypeError("检查点内容不是字典。")

    checkpoint = dict(checkpoint_raw)
    architecture_raw = checkpoint.get("architecture", {})
    state_dict_raw = checkpoint.get("model_state_dict")
    normalizers_raw = checkpoint.get("normalizers")

    if not isinstance(architecture_raw, Mapping):
        raise KeyError("检查点 architecture 字段无效。")

    if not isinstance(state_dict_raw, Mapping):
        raise KeyError("检查点缺少 model_state_dict。")

    if not isinstance(normalizers_raw, Mapping):
        raise KeyError("检查点缺少 normalizers。")

    architecture = dict(architecture_raw)
    model_type = clean_text(
        architecture.get("model_type")
    )

    if model_type != "PhysicsGuidedDualTaskGNN":
        raise RuntimeError(
            "当前正向预测代码只接受双任务检查点，"
            f"实际model_type={model_type!r}。"
        )

    required_normalizers = (
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

    missing = [
        name
        for name in required_normalizers
        if name not in normalizers_raw
    ]

    if missing:
        raise KeyError(
            "检查点缺少标准化参数："
            + ", ".join(missing)
        )

    normalizers = {
        name: normalizers_raw[name]
        for name in required_normalizers
    }

    in_channels = int(
        architecture.get(
            "in_channels",
            normalizers["x_mean"].numel(),
        )
    )
    edge_dim = int(
        architecture.get(
            "edge_dim",
            normalizers["edge_mean"].numel(),
        )
    )
    global_feature_dim = int(
        architecture.get(
            "global_feature_dim",
            normalizers["u_mean"].numel(),
        )
    )

    if in_channels != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError(
            f"检查点节点输入维度不是15：{in_channels}"
        )

    if edge_dim != EXPECTED_EDGE_FEATURE_DIM:
        raise RuntimeError(
            f"检查点边特征维度不是9：{edge_dim}"
        )

    if global_feature_dim != EXPECTED_GLOBAL_FEATURE_DIM:
        raise RuntimeError(
            f"检查点入口维度不是2：{global_feature_dim}"
        )

    chip_dim = int(
        architecture.get(
            "chip_physics_feature_dim",
            EXPECTED_CHIP_PHYSICS_DIM,
        )
    )

    if chip_dim != EXPECTED_CHIP_PHYSICS_DIM:
        raise RuntimeError(
            f"检查点chip_physics维度不是7：{chip_dim}"
        )

    model = PhysicsGuidedDualTaskGNN(
        in_channels=in_channels,
        edge_dim=edge_dim,
        global_feature_dim=global_feature_dim,
        hidden_channels=int(
            architecture.get("hidden_channels", 128)
        ),
        heads=int(architecture.get("heads", 4)),
        num_layers=int(
            architecture.get(
                "layers",
                architecture.get("num_layers", 3),
            )
        ),
        dropout=float(architecture.get("dropout", 0.1)),
        use_edge_attr=bool(
            architecture.get("use_edge_attr", True)
        ),
        x_mean=normalizers["x_mean"],
        x_std=normalizers["x_std"],
        u_mean=normalizers["u_mean"],
        u_std=normalizers["u_std"],
        flow_log_mean=normalizers["flow_log_mean"],
        flow_log_std=normalizers["flow_log_std"],
    )

    try:
        model.load_state_dict(
            dict(state_dict_raw),
            strict=True,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            "已找到双任务检查点，但网络参数与训练代码不一致。\n"
            f"检查点：{checkpoint_path}\n"
            f"原始错误：{exc}"
        ) from exc

    model.to(device)
    model.eval()

    return LoadedPhysicsModel(
        model=model,
        checkpoint=checkpoint,
        normalizers=normalizers,
        checkpoint_path=checkpoint_path,
        model_type=model_type,
    )


# =============================================================================
# 8. 推理
# =============================================================================

def build_normalized_batch(
    samples: Sequence[InputSample],
    model_info: LoadedPhysicsModel,
    device: torch.device,
) -> Tuple[Any, List[Dict[str, Any]]]:
    if Batch is None or Data is None:
        raise ImportError(
            "正式 Physics-GNN 预测需要安装 torch_geometric。"
        )

    graphs: List[Any] = []
    audits: List[Dict[str, Any]] = []
    normalizers = model_info.normalizers

    for sample in samples:
        raw_x = build_raw_x(sample)
        raw_edge_index, raw_edge_attr = build_raw_edges(sample)
        raw_u = build_raw_u(sample)
        raw_chip_physics = build_raw_chip_physics(sample)

        normalized_x = normalize_tensor(
            raw_x,
            normalizers["x_mean"],
            normalizers["x_std"],
            "x",
        )
        normalized_edge_attr = normalize_tensor(
            raw_edge_attr,
            normalizers["edge_mean"],
            normalizers["edge_std"],
            "edge_attr",
        )
        normalized_u = normalize_tensor(
            raw_u,
            normalizers["u_mean"],
            normalizers["u_std"],
            "u",
        )
        chip_physics_z = normalize_tensor(
            raw_chip_physics,
            normalizers["chip_physics_mean"],
            normalizers["chip_physics_std"],
            "chip_physics",
        )

        graph = Data(
            x=normalized_x,
            edge_index=raw_edge_index,
            edge_attr=normalized_edge_attr,
            u=normalized_u,
            chip_physics=raw_chip_physics,
            chip_physics_z=chip_physics_z,
        )
        graph.sample_name = sample.sample_name
        graphs.append(graph)

        x_abs_z = normalized_x.abs()
        edge_abs_z = normalized_edge_attr.abs()
        u_abs_z = normalized_u.abs()
        chip_abs_z = chip_physics_z.abs()

        audits.append({
            "sample_name": sample.sample_name,
            "model_type": model_info.model_type,
            "x_shape": str(tuple(raw_x.shape)),
            "edge_index_shape": str(tuple(raw_edge_index.shape)),
            "edge_attr_shape": str(tuple(raw_edge_attr.shape)),
            "u_shape": str(tuple(raw_u.shape)),
            "chip_physics_shape": str(tuple(raw_chip_physics.shape)),
            "x_max_abs_z": float(x_abs_z.max().item()),
            "edge_max_abs_z": float(edge_abs_z.max().item()),
            "u_max_abs_z": float(u_abs_z.max().item()),
            "chip_physics_max_abs_z": float(chip_abs_z.max().item()),
            "x_count_abs_z_gt3": int((x_abs_z > Z_WARNING_THRESHOLD).sum().item()),
            "edge_count_abs_z_gt3": int((edge_abs_z > Z_WARNING_THRESHOLD).sum().item()),
            "u_count_abs_z_gt3": int((u_abs_z > Z_WARNING_THRESHOLD).sum().item()),
            "chip_physics_count_abs_z_gt3": int((chip_abs_z > Z_WARNING_THRESHOLD).sum().item()),
            "x_count_abs_z_gt5": int((x_abs_z > Z_SEVERE_THRESHOLD).sum().item()),
            "edge_count_abs_z_gt5": int((edge_abs_z > Z_SEVERE_THRESHOLD).sum().item()),
            "u_count_abs_z_gt5": int((u_abs_z > Z_SEVERE_THRESHOLD).sum().item()),
            "chip_physics_count_abs_z_gt5": int((chip_abs_z > Z_SEVERE_THRESHOLD).sum().item()),
        })

    return Batch.from_data_list(graphs).to(device), audits


@torch.no_grad()
def predict(
    samples: Sequence[InputSample],
    model_info: LoadedPhysicsModel,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]]]:
    batch, audits = build_normalized_batch(
        samples,
        model_info,
        device,
    )

    output = model_info.model(batch)

    if not isinstance(output, Mapping):
        raise TypeError("双任务模型输出必须为字典。")

    concentration = output.get("concentration")
    flow = output.get("flow")

    if not torch.is_tensor(concentration):
        raise RuntimeError("模型输出缺少 concentration。")

    if not torch.is_tensor(flow):
        raise RuntimeError("模型输出缺少 flow。")

    concentration_np = (
        concentration.detach().cpu().numpy().astype(np.float64)
    )
    flow_np = flow.detach().cpu().numpy().astype(np.float64)

    expected_shape = (len(samples), EXPECTED_OUTPUT_DIM)

    if concentration_np.shape != expected_shape:
        raise RuntimeError(
            f"浓度输出shape应为{expected_shape}，"
            f"实际为{concentration_np.shape}"
        )

    if flow_np.shape != expected_shape:
        raise RuntimeError(
            f"流量输出shape应为{expected_shape}，"
            f"实际为{flow_np.shape}"
        )

    if CLIP_PREDICTION_TO_01:
        concentration_np = np.clip(
            concentration_np,
            BOUNDARY_MIN,
            BOUNDARY_MAX,
        )

    return concentration_np, flow_np, audits


# =============================================================================
# 9. 结果输出
# =============================================================================

def safe_column_name(text: str) -> str:
    value = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff]+",
        "_",
        text,
    ).strip("_")

    return value or "unknown"


def save_results(
    samples: Sequence[InputSample],
    concentration_predictions: np.ndarray,
    flow_predictions: np.ndarray,
    output_path: Path,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    for sample_index, sample in enumerate(samples):
        concentration_values = concentration_predictions[sample_index]
        flow_values = flow_predictions[sample_index]

        row: Dict[str, Any] = {
            "sample_name": sample.sample_name,
            "inlet1": sample.inlet1,
            "inlet2": sample.inlet2,
            "model": "PhysicsGuidedDualTaskGNN",
            "order_definition": (
                "table_left_to_right="
                "image_top_to_bottom="
                "chip1_to_chip6="
                "y1_q1_to_y6_q6"
            ),
            "concentration_min": float(concentration_values.min()),
            "concentration_max": float(concentration_values.max()),
            "boundary_violation_count": int(
                np.sum(
                    (concentration_values < BOUNDARY_MIN)
                    | (concentration_values > BOUNDARY_MAX)
                )
            ),
            "predicted_total_outlet_flow_kg_s": float(flow_values.sum()),
        }

        for outlet_index, chip in enumerate(sample.chips):
            number = outlet_index + 1
            chip_token = safe_column_name(chip.chip_name)

            row[f"y{number}_chip_name"] = chip.chip_name
            row[f"y{number}_{chip_token}_pred"] = float(
                concentration_values[outlet_index]
            )
            row[f"q{number}_{chip_token}_pred_kg_s"] = float(
                flow_values[outlet_index]
            )

        rows.append(row)

    dataframe = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )
    return dataframe


def print_results(
    samples: Sequence[InputSample],
    concentration_predictions: np.ndarray,
    flow_predictions: np.ndarray,
    audits: Sequence[Mapping[str, Any]],
) -> None:
    print()
    print("=" * 96)
    print("Physics-GNN V4 双任务正向预测结果")
    print("顺序：表格从左到右 = 图片从上到下 = y1/q1 ~ y6/q6")
    print("=" * 96)

    for sample_index, sample in enumerate(samples):
        print()
        print("-" * 96)
        print("样本：", sample.sample_name)
        print(
            f"入口浓度：inlet1={sample.inlet1:.8f}, "
            f"inlet2={sample.inlet2:.8f}"
        )
        print("-" * 96)

        for outlet_index, chip in enumerate(sample.chips):
            concentration = float(
                concentration_predictions[sample_index, outlet_index]
            )
            flow = float(
                flow_predictions[sample_index, outlet_index]
            )

            warning = ""
            if concentration < BOUNDARY_MIN or concentration > BOUNDARY_MAX:
                warning = " [浓度超出0~1]"

            position_text = (
                "最上方"
                if outlet_index == 0
                else (
                    "最下方"
                    if outlet_index == 5
                    else f"第{outlet_index + 1}个"
                )
            )

            print(
                f"y{outlet_index + 1} "
                f"({chip.chip_name}, {position_text})："
                f"{concentration:.10f}{warning} | "
                f"q{outlet_index + 1}="
                f"{flow:.12e} kg/s"
            )

        print(
            "预测总出口流量：",
            f"{float(flow_predictions[sample_index].sum()):.12e} kg/s",
        )

        audit = audits[sample_index]
        print(
            "输入分布检查："
            f"x max|z|={audit['x_max_abs_z']:.6f}, "
            f"edge max|z|={audit['edge_max_abs_z']:.6f}, "
            f"u max|z|={audit['u_max_abs_z']:.6f}, "
            "chip_physics max|z|="
            f"{audit['chip_physics_max_abs_z']:.6f}"
        )

        if (
            audit["x_count_abs_z_gt5"] > 0
            or audit["edge_count_abs_z_gt5"] > 0
            or audit["u_count_abs_z_gt5"] > 0
            or audit["chip_physics_count_abs_z_gt5"] > 0
        ):
            print(
                "[警告] 部分输入明显超出训练集单变量范围，"
                "必须与CFD结果进行盲测核验。"
            )

    print()
    print("=" * 96)


# =============================================================================
# 10. 参数与主程序
# =============================================================================

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "使用 Physics-GNN 实验D双任务模型预测六出口浓度和流量。"
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="正向预测 CSV/XLSX/XLS。",
    )

    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="实验D best_concentration_checkpoint.pt；不指定则自动查找。",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析输入和构图，不加载模型。",
    )

    return parser


def main() -> None:
    args = build_argument_parser().parse_args()

    try:
        project_root = find_project_root(
            SCRIPT_DIR
        )
    except FileNotFoundError:
        project_root = None

    input_path = find_input_file(
        args.input
    )

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else OUTPUT_DIR.resolve()
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path = (
        output_dir
        / RESULT_FILENAME
    )

    audit_path = (
        output_dir
        / GRAPH_AUDIT_FILENAME
    )

    run_info_path = (
        output_dir
        / RUN_INFO_FILENAME
    )

    samples = parse_input_samples(
        input_path
    )

    # 先无条件完成原始图构建，确保输入含义正确。
    raw_graph_audits: List[Dict[str, Any]] = []

    for sample in samples:
        raw_x = build_raw_x(sample)
        raw_edge_index, raw_edge_attr = (
            build_raw_edges(sample)
        )
        raw_u = build_raw_u(sample)
        raw_chip_physics = build_raw_chip_physics(sample)

        raw_graph_audits.append({
            "sample_name": sample.sample_name,
            "chip_order": ",".join(
                chip.chip_name
                for chip in sample.chips
            ),
            "mapping": (
                "P1+P2->y1;P3+P4->y2;"
                "P5+P6->y3;P7+P8->y4;"
                "P9+P10->y5;P11+P12->y6"
            ),
            "x_shape": str(tuple(raw_x.shape)),
            "edge_index_shape": str(
                tuple(raw_edge_index.shape)
            ),
            "edge_attr_shape": str(
                tuple(raw_edge_attr.shape)
            ),
            "u_shape": str(tuple(raw_u.shape)),
            "chip_physics_shape": str(tuple(raw_chip_physics.shape)),
        })

    dataset_path = find_optional_dataset(
        project_root
    )

    dataset_validation = (
        validate_against_training_dataset(
            dataset_path,
            samples[0],
        )
    )

    print()
    print("=" * 90)
    print("Physics-GNN V4 双任务正向预测")
    print("=" * 90)
    print("输入表：", input_path)
    print("样本数：", len(samples))
    print(
        "顺序定义：P1+P2 到 P11+P12，"
        "对应图片从上到下 y1~y6"
    )
    print(
        "构图：8节点、24条边、"
        "15维节点特征、9维边特征、7维芯片物理特征、2维入口"
    )

    if dataset_path is not None:
        print("训练数据结构校验：通过")
        print("训练数据：", dataset_path)
    else:
        print(
            "[提示] 未找到本地 physics_gnn_dataset.pt，"
            "已按固定新版规则完成构图。"
        )

    if args.dry_run:
        pd.DataFrame(
            raw_graph_audits
        ).to_csv(
            audit_path,
            index=False,
            encoding="utf-8-sig",
        )

        write_json(
            run_info_path,
            {
                "mode": "dry_run",
                "input_path": str(input_path),
                "input_sha256": sha256_file(
                    input_path
                ),
                "sample_count": len(samples),
                "dataset_validation": (
                    dataset_validation
                ),
                "graph_audit_path": str(
                    audit_path
                ),
            },
        )

        print("Dry run：构图检查通过")
        print("构图审计：", audit_path)
        print("运行信息：", run_info_path)
        print("=" * 90)
        return

    checkpoint_path = find_checkpoint(
        args.checkpoint,
        project_root,
    )

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )

    print("检查点：", checkpoint_path)
    print("设备：", device)

    model_info = load_dualtask_model(
        checkpoint_path,
        device,
    )

    concentration_predictions, flow_predictions, normalized_audits = (
        predict(
            samples,
            model_info,
            device,
        )
    )

    print(
        "检查点 Seed：",
        model_info.checkpoint.get(
            "seed",
            "unknown",
        ),
    )

    print(
        "最佳 Epoch：",
        model_info.checkpoint.get(
            "best_epoch",
            "unknown",
        ),
    )

    print(
        "最佳验证浓度 RMSE：",
        model_info.checkpoint.get(
            "best_val_concentration_rmse",
            "unknown",
        ),
    )

    print_results(
        samples,
        concentration_predictions,
        flow_predictions,
        normalized_audits,
    )

    save_results(
        samples,
        concentration_predictions,
        flow_predictions,
        result_path,
    )

    pd.DataFrame(
        normalized_audits
    ).to_csv(
        audit_path,
        index=False,
        encoding="utf-8-sig",
    )

    write_json(
        run_info_path,
        {
            "program": (
                "forward_predict_dualtask_v4.py"
            ),
            "model": "PhysicsGuidedDualTaskGNN",
            "experiment_type": (
                model_info.checkpoint.get(
                    "experiment_type"
                )
            ),
            "checkpoint_path": str(
                checkpoint_path
            ),
            "checkpoint_sha256": (
                sha256_file(
                    checkpoint_path
                )
            ),
            "checkpoint_seed": (
                model_info.checkpoint.get(
                    "seed"
                )
            ),
            "checkpoint_best_epoch": (
                model_info.checkpoint.get(
                    "best_epoch"
                )
            ),
            "checkpoint_best_val_concentration_rmse": (
                model_info.checkpoint.get(
                    "best_val_concentration_rmse"
                )
            ),
            "checkpoint_best_val_flow_log_rmse": (
                model_info.checkpoint.get(
                    "best_val_flow_log_rmse"
                )
            ),
            "checkpoint_dataset_sha256": (
                model_info.checkpoint.get(
                    "dataset_sha256"
                )
            ),
            "input_path": str(input_path),
            "input_sha256": sha256_file(
                input_path
            ),
            "sample_count": len(samples),
            "device": str(device),
            "order_definition": (
                "table_left_to_right="
                "image_top_to_bottom="
                "P1P2_to_P11P12="
                "y1_to_y6"
            ),
            "graph_structure": {
                "node_count": 8,
                "node_feature_dim": 15,
                "edge_count": 24,
                "edge_feature_dim": 9,
                "global_feature_dim": 2,
                "chip_physics_shape": [6, 7],
                "concentration_output_dim": 6,
                "flow_output_dim": 6,
            },
            "node_feature_names": list(
                NODE_FEATURE_NAMES
            ),
            "edge_feature_names": list(
                EDGE_FEATURE_NAMES
            ),
            "chip_physics_feature_names": list(
                CHIP_PHYSICS_FEATURE_NAMES
            ),
            "uses_mass_flow_as_input": False,
            "predicts_outlet_flow": True,
            "clip_prediction_to_01": (
                CLIP_PREDICTION_TO_01
            ),
            "dataset_validation": (
                dataset_validation
            ),
            "result_path": str(
                result_path
            ),
            "graph_audit_path": str(
                audit_path
            ),
        },
    )

    print("预测结果：", result_path)
    print("构图/分布审计：", audit_path)
    print("运行信息：", run_info_path)
    print("=" * 90)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 90)
        print("[Physics-GNN V4 双任务正向预测失败]")
        print(
            type(exc).__name__
            + "：",
            exc,
        )
        print("=" * 90)
        raise
