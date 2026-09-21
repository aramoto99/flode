"""ADR-0079 Stage 3 (D-9) の migration 基準モデル (schema 0.14 → 0.15 の数値等価検証用)。

0.14 までの ``StateSpace`` / ``DiscreteStateSpace`` / ``MimoTransferFunction`` は
入力 m 本 / 出力 p 本の **スカラポート** を持っていた。0.15 (v0.64.0) で
ベクトルポート 1 本に統一され、既存ファイルは migration が ``Mux`` / ``Demux`` を
挿入して結線を付け替える。本モジュールは

1. 0.14 形式の fixture (``tests/data/lti_ports_0_14.flw.json``) を **辞書として保持**し
   (0.15 以降の Python API では m 本ポート形式を構築できないため JSON 直書き)、
2. v0.63.0 (= 0.14 が current だった最後の版) で採取した実行結果
   (``tests/data/lti_migration_baseline_v0_63_0.npz``)

を提供する。``test_persistence_migration_0_14_to_0_15.py`` が fixture を migrate →
run して npz と ``np.array_equal`` で突合する。``__main__`` 実行で両ファイルを (再) 採取する
(採取は **0.14 が current の版で** 行うこと。0.15 以降では migration 後の結果になる)。

固定条件は ``_dtype_baseline_models`` と同じ (dt = 1/64、RK45、rtol/atol 明示、RandomSource なし)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from flode import Simulator

logger = logging.getLogger(__name__)

_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
FIXTURE_JSON: Path = _DATA_DIR / "lti_ports_0_14.flw.json"
BASELINE_NPZ: Path = _DATA_DIR / "lti_migration_baseline_v0_63_0.npz"

T_END: float = 1.0
DT: float = 0.015625  # 1/64
DSS_SAMPLE_TIME: float = 0.0625  # 4 * DT
SOLVER: str = "RK45"
RTOL: float = 1e-6
ATOL: float = 1e-9

_SS = "flode.blocks.continuous.StateSpace"
_DSS = "flode.blocks.discrete.DiscreteStateSpace"
_MIMO = "flode.blocks.continuous.MimoTransferFunction"
_SUB = "flode.subsystems.subsystem.Subsystem"
_INPORT = "flode.subsystems.ports.Inport"
_OUTPORT = "flode.subsystems.ports.Outport"
_SCOPE = "flode.blocks.sinks.Scope"
_STEP = "flode.blocks.sources.Step"
_SINE = "flode.blocks.sources.Sine"

SCOPE_LABELS: tuple[str, ...] = (
    "ss0",
    "ss1",
    "dss0",
    "dss1",
    "mimo0",
    "mimo1",
    "siso",
    "sub0",
    "sub1",
)


def _conn(src: str, src_idx: int, dst: str, dst_idx: int) -> dict[str, Any]:
    return {"src": src, "src_idx": src_idx, "dst": dst, "dst_idx": dst_idx}


def fixture_0_14() -> dict[str, Any]:
    """0.14 形式の migration fixture を **新しい辞書** で返す。

    内容 (すべて m = 2 / p = 2 の旧スカラポート形式、SISO 1 個は対象外の証明用):

    - ``ss``: 減衰振動子 (連続 StateSpace 2×2)、入力 = (step, sine)、出力 2 本 → scope
    - ``dss``: 離散 StateSpace 2×2 (sample_time = 4 dt)
    - ``mimo``: 対角 MIMO TF p = 2 / q = 2
    - ``siso``: 1 次遅れ (m = p = 1、migration 対象外)
    - ``sub``: Subsystem 内に StateSpace 2×2 (ネスト再帰の検証)
    - layout は全ブロックに付け、``branch_waypoints`` は ``ss:1`` / ``mimo:0`` に付ける
    """
    inner_blocks = [
        {"id": "in0", "type": _INPORT, "params": {"port_idx": 0}},
        {"id": "in1", "type": _INPORT, "params": {"port_idx": 1}},
        {
            "id": "ss_in",
            "type": _SS,
            "params": {
                "A": [[0.0, 1.0], [-3.0, -0.4]],
                "B": [[0.0, 1.0], [1.0, 0.0]],
                "C": [[1.0, 0.0], [0.0, 1.0]],
                "D": [[0.0, 0.0], [0.0, 0.0]],
                "x0": [0.5, 0.0],
            },
        },
        {"id": "out0", "type": _OUTPORT, "params": {"port_idx": 0}},
        {"id": "out1", "type": _OUTPORT, "params": {"port_idx": 1}},
    ]
    inner_conns = [
        _conn("in0", 0, "ss_in", 0),
        _conn("in1", 0, "ss_in", 1),
        _conn("ss_in", 0, "out0", 0),
        _conn("ss_in", 1, "out1", 0),
    ]
    inner_layout = {
        "in0": {"x": 0.0, "y": 0.0},
        "in1": {"x": 0.0, "y": 80.0},
        "ss_in": {"x": 200.0, "y": 40.0},
        "out0": {"x": 400.0, "y": 0.0},
        "out1": {"x": 400.0, "y": 80.0},
    }
    blocks = [
        {
            "id": "step",
            "type": _STEP,
            "params": {"step_time": 0.25, "initial_value": 0.0, "final_value": 1.0},
        },
        {
            "id": "sine",
            "type": _SINE,
            "params": {"amplitude": 0.5, "frequency": 1.0, "phase": 0.0},
        },
        {
            "id": "ss",
            "type": _SS,
            "params": {
                "A": [[0.0, 1.0], [-2.0, -0.5]],
                "B": [[1.0, 0.0], [0.0, 1.0]],
                "C": [[1.0, 0.0], [0.0, 1.0]],
                "D": [[0.0, 0.0], [0.0, 0.0]],
                "x0": [1.0, 0.0],
            },
        },
        {
            "id": "dss",
            "type": _DSS,
            "params": {
                "A": [[0.9, 0.1], [0.0, 0.8]],
                "B": [[1.0, 0.0], [0.0, 1.0]],
                "C": [[1.0, 1.0], [1.0, -1.0]],
                "D": [[0.0, 0.0], [0.0, 0.0]],
                "x0": [0.0, 0.0],
                "sample_time": DSS_SAMPLE_TIME,
            },
        },
        {
            "id": "mimo",
            "type": _MIMO,
            "params": {
                "numerators": [[[1.0], [0.0]], [[0.0], [2.0]]],
                "denominator": [1.0, 1.0],
                "x0": [0.0, 0.0, 0.0, 0.0],
            },
        },
        {
            "id": "siso",
            "type": _SS,
            "params": {
                "A": [[-1.0]],
                "B": [[1.0]],
                "C": [[1.0]],
                "D": [[0.0]],
                "x0": [0.0],
            },
        },
        {
            "id": "sub",
            "type": _SUB,
            "params": {
                "blocks": inner_blocks,
                "connections": inner_conns,
                "layout": inner_layout,
            },
        },
        {
            "id": "scope",
            "type": _SCOPE,
            "params": {
                "n_inputs": len(SCOPE_LABELS),
                "labels": list(SCOPE_LABELS),
                "buffer_mode": "ring",
                "buffer_capacity": 100000,
            },
        },
    ]
    connections = [
        _conn("step", 0, "ss", 0),
        _conn("sine", 0, "ss", 1),
        _conn("step", 0, "dss", 0),
        _conn("sine", 0, "dss", 1),
        _conn("step", 0, "mimo", 0),
        _conn("sine", 0, "mimo", 1),
        _conn("step", 0, "siso", 0),
        _conn("step", 0, "sub", 0),
        _conn("sine", 0, "sub", 1),
        _conn("ss", 0, "scope", 0),
        _conn("ss", 1, "scope", 1),
        _conn("dss", 0, "scope", 2),
        _conn("dss", 1, "scope", 3),
        _conn("mimo", 0, "scope", 4),
        _conn("mimo", 1, "scope", 5),
        _conn("siso", 0, "scope", 6),
        _conn("sub", 0, "scope", 7),
        _conn("sub", 1, "scope", 8),
    ]
    layout = {
        "step": {"x": 0.0, "y": 0.0},
        "sine": {"x": 0.0, "y": 120.0},
        "ss": {"x": 300.0, "y": 0.0},
        "dss": {"x": 300.0, "y": 120.0},
        "mimo": {"x": 300.0, "y": 240.0},
        "siso": {"x": 300.0, "y": 360.0},
        "sub": {"x": 300.0, "y": 480.0},
        "scope": {"x": 700.0, "y": 200.0},
    }
    return {
        "schema_version": "0.14",
        "metadata": {"created_at": "2026-09-21T00:00:00Z", "tool": "flode 0.63.0"},
        "simulator": {
            "t_end": T_END,
            "dt": DT,
            "solver": SOLVER,
            "rtol": RTOL,
            "atol": ATOL,
            "dt_base": None,
        },
        "blocks": blocks,
        "connections": connections,
        "layout": layout,
        "branch_waypoints": {
            "ss:1": [{"x": 500.0, "y": 60.0}],
            "mimo:0": [{"x": 500.0, "y": 250.0}],
        },
    }


def run_model(data: dict[str, Any]) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """モデル辞書 (0.14 でも 0.15 でも) を load して run し ``(times, values)`` を返す。"""
    sim = Simulator.from_dict(data)
    sim.run()
    scope = sim.get_block("scope")
    times = np.asarray(list(scope.times), dtype=np.float64)
    values = np.asarray(scope.values, dtype=np.float64)
    return times, values


def _main() -> None:
    """fixture JSON と基準 npz を採取する (0.14 が current の版で実行すること)。"""
    import scipy

    data = fixture_0_14()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    times, values = run_model(fixture_0_14())
    np.savez(
        BASELINE_NPZ,
        numpy_version=np.array(np.__version__),
        scipy_version=np.array(scipy.__version__),
        times=times,
        values=values,
    )
    logger.info("fixture written: %s", FIXTURE_JSON)
    logger.info("baseline written: %s (values shape=%s)", BASELINE_NPZ, values.shape)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _main()
