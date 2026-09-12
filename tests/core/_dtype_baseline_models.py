"""SPEC-0027 AC-3 の基準モデル群 (SM-D Stage 0 の挙動不変性検証用)。

3 つの代表モデル (連続 / 離散 / Cast+論理混在) を構築する helper。
`test_dtypes_no_behavior_change.py` が import して

1. 「``run()`` のみ」と「``resolve_dtypes()`` を挟んだ ``run()``」の
   同一プロセス bit-identical 比較 (主防衛線)、
2. v0.53.7 時点で採取した基準 npz (``tests/data/dtypes_baseline_v0_53_7.npz``)
   との ``np.array_equal`` 比較 (クロスバージョン保証の追加層)

の両方に使う。``__main__`` 実行で npz を (再) 採取する。

設計上の固定条件 (SPEC-0027 §AC-3 / 実装計画 Phase 0):

- ソルバ設定はすべて明示 (``t_end=1.0, dt=0.015625, solver="RK45",
  rtol=1e-6, atol=1e-9``)。既定値の将来変更に対する防御。
  ``dt = 1/64`` は二進で正確に表現でき、時間格子に丸め誤差を持ち込まない
- 記録格子は固定 macro step (``dt``) なので solve_ivp の適応刻みに依存しない
- ``RandomSource`` は使わない (seed 依存の排除)
- 採取した npz には numpy / scipy のバージョンをメタとして同梱し、
  差分検出時に環境起因かコード起因かを切り分けられるようにする
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from flode import Simulator
from flode.blocks.continuous import Integrator
from flode.blocks.discrete import UnitDelay
from flode.blocks.mathops import CompareToConstant, CompareToZero, Gain, Sum
from flode.blocks.routing import Switch
from flode.blocks.sinks import Scope
from flode.blocks.sources import Clock, Constant

logger = logging.getLogger(__name__)

Builder = Callable[[], tuple[Simulator, Scope]]

# ソルバ設定 (明示固定、SPEC-0027 §AC-3)
T_END: float = 1.0
DT: float = 0.015625  # 1/64 — 二進で正確
SOLVER: str = "RK45"
RTOL: float = 1e-6
ATOL: float = 1e-9

# 採取先 (tests/data/ 配下、ファイル名に採取元バージョンを刻む)
BASELINE_NPZ: Path = Path(__file__).resolve().parent.parent / "data" / "dtypes_baseline_v0_53_7.npz"

# ばね-質量-減衰系の物理定数 (m=1 に正規化済み)
_DAMPING_C: float = 0.5
_STIFFNESS_K: float = 2.0
_INITIAL_POSITION: float = 1.0


def _new_simulator() -> Simulator:
    """固定ソルバ設定の Simulator を返す。"""
    return Simulator(t_end=T_END, dt=DT, solver=SOLVER, rtol=RTOL, atol=ATOL)


def build_continuous() -> tuple[Simulator, Scope]:
    """連続系: ばね-質量-減衰 (m=1, c=0.5, k=2, x(0)=1, v(0)=0)。

    x'' = -c*v - k*x を Integrator×2 + Gain×2 + Sum で構成する。
    solve_ivp (連続状態) に触れる唯一の基準モデル。

    Returns:
        (Simulator, 位置と速度を記録する Scope)
    """
    sim = _new_simulator()
    sum_acc = sim.add(Sum(signs="--", id="sum_acc"))
    integ_v = sim.add(Integrator(x0=0.0, id="integ_v"))
    integ_x = sim.add(Integrator(x0=_INITIAL_POSITION, id="integ_x"))
    gain_c = sim.add(Gain(k=_DAMPING_C, id="gain_c"))
    gain_k = sim.add(Gain(k=_STIFFNESS_K, id="gain_k"))
    scope = sim.add(Scope(n_inputs=2, labels=["x", "v"], id="scope"))

    sim.connect(sum_acc, integ_v)  # a -> v
    sim.connect(integ_v, integ_x)  # v -> x
    sim.connect(integ_v, gain_c)
    sim.connect(integ_x, gain_k)
    sim.connect(gain_c, sum_acc, dst_idx=0)  # -c*v
    sim.connect(gain_k, sum_acc, dst_idx=1)  # -k*x
    sim.connect(integ_x, scope, dst_idx=0)
    sim.connect(integ_v, scope, dst_idx=1)
    return sim, scope


def build_discrete() -> tuple[Simulator, Scope]:
    """離散系: Constant → Sum → UnitDelay → Sum の帰還 (累積カウンタ)。

    連続状態を持たず、UnitDelay (direct_feedthrough=False) がループを切る。
    dtype 面では Constant/Sum/UnitDelay の promote 経路と不動点反復を代表する。

    Returns:
        (Simulator, 累積値を記録する Scope)
    """
    sim = _new_simulator()
    const = sim.add(Constant(value=1.0, id="const"))
    sum_fb = sim.add(Sum(signs="++", id="sum_fb"))
    delay = sim.add(UnitDelay(sample_time=DT, x0=0.0, id="delay"))
    scope = sim.add(Scope(n_inputs=1, labels=["acc"], id="scope"))

    sim.connect(const, sum_fb, dst_idx=0)
    sim.connect(delay, sum_fb, dst_idx=1)
    sim.connect(sum_fb, delay)
    sim.connect(sum_fb, scope)
    return sim, scope


def build_mixed() -> tuple[Simulator, Scope]:
    """混在系: Constant → CompareToZero → 比較 → Switch。

    論理/比較/ルーティングを含み、dtype 面では param_typed / bool_out /
    promote_except_control を代表する。Clock を足して時間依存にし、
    bit 比較を意味のあるものにする。

    v0.56.0 (output_type 撤去) での等価置換 — **基準 npz は不変**:
    ``Constant(value=2.7, output_type="int")`` (→ 3.0) は
    ``Constant(value=3.0)`` に、``Cast(output_type="bool")`` (u != 0 → 1.0) は
    ``CompareToZero(op="!=")`` に置換した。どちらも出力値が同一の float64 で、
    dtype 宣言を含まないため SM-A 経路も維持される。

    Returns:
        (Simulator, Switch+Clock の和を記録する Scope)
    """
    sim = _new_simulator()
    c_int = sim.add(Constant(value=3.0, id="c_int"))  # -> 3.0
    cast_b = sim.add(CompareToZero(op="!=", id="cast_b"))  # -> 1.0
    cmp = sim.add(CompareToConstant(op=">", const=0.5, id="cmp"))  # -> 1.0
    c_false = sim.add(Constant(value=-1.0, id="c_false"))
    sw = sim.add(Switch(threshold=0.5, criterion=">=", id="sw"))
    clock = sim.add(Clock(id="clock"))
    sum_m = sim.add(Sum(signs="++", id="sum_m"))
    scope = sim.add(Scope(n_inputs=1, labels=["y"], id="scope"))

    sim.connect(c_int, cast_b)
    sim.connect(cast_b, cmp)
    sim.connect(c_int, sw, dst_idx=0)  # input_true = 3.0
    sim.connect(cmp, sw, dst_idx=1)  # control = 1.0
    sim.connect(c_false, sw, dst_idx=2)  # input_false
    sim.connect(sw, sum_m, dst_idx=0)
    sim.connect(clock, sum_m, dst_idx=1)
    sim.connect(sum_m, scope)
    return sim, scope


def builders() -> tuple[tuple[str, Builder], ...]:
    """(名前, builder) の一覧。テストと採取の両方が同じ順で使う。"""
    return (
        ("continuous", build_continuous),
        ("discrete", build_discrete),
        ("mixed", build_mixed),
    )


def run_and_capture(builder: Builder) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """builder のモデルを run し (times, values) を float64 配列で返す。"""
    sim, scope = builder()
    sim.run()
    times = np.asarray(list(scope.times), dtype=np.float64)
    values = np.asarray(scope.values, dtype=np.float64)
    return times, values


def capture_all() -> dict[str, npt.NDArray[np.float64]]:
    """3 モデルすべてを run し、npz 保存キー → 配列の辞書を返す。"""
    arrays: dict[str, npt.NDArray[np.float64]] = {}
    for name, builder in builders():
        times, values = run_and_capture(builder)
        arrays[f"{name}_times"] = times
        arrays[f"{name}_values"] = values
    return arrays


def _main() -> None:
    """基準 npz を採取して ``BASELINE_NPZ`` に書き出す。"""
    import scipy

    arrays = capture_all()
    BASELINE_NPZ.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        BASELINE_NPZ,
        numpy_version=np.array(np.__version__),
        scipy_version=np.array(scipy.__version__),
        **arrays,
    )
    for key, arr in arrays.items():
        logger.info("captured %s: shape=%s", key, arr.shape)
    logger.info("baseline written: %s", BASELINE_NPZ)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _main()
