"""ADR-0014 エッジケース・境界値テスト。

実装完了後の網羅的テスト (test-writer agent)。

カバー範囲:
- ZeroOrderHoldDirect: JSON round-trip (ADR-0008), sample_time 不正値,
  sample_time=-1.0 継承, 浮動小数サンプル時刻判定の境界値
- Simulator loop (ADR-0014 §(1)): on_step_callback のタイミング,
  request_stop() graceful stop
- Subsystem (ADR-0009) 内離散ブロックの ADR-0014 semantics
- DiscreteTransferFunction 2 次系の標準形
- DiscreteStateSpace 2 次安定系の標準形
- multi-rate UnitDelay の off-by-one 既知制限の定量化 (ADR-0014 §Risks #1)

参照:
- ADR-0014 §(1)(3) ループ構造 / ZOHDirect 仕様
- ADR-0008 JSON 永続化
- ADR-0009 Subsystem
- ADR-0014 §Risks #6 Subsystem 相互作用
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Clock,
    Constant,
    DiscreteIntegrator,
    DiscreteStateSpace,
    DiscreteTransferFunction,
    Scope,
    UnitDelay,
    ZeroOrderHoldDirect,
)
from flode.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    """Scope.values (n_time, n_inputs) を 1D に flatten して返す (SISO 用)。"""
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# 1. ZeroOrderHoldDirect JSON round-trip (ADR-0008)
# ---------------------------------------------------------------------------


@pytest.fixture
def _zohd_persisted(tmp_path):
    """ZOHDirect を含む sim を save/load して、type/sample_time/x0 をまとめて検証可能にする。"""
    sim = Simulator(t_end=0.03, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    sim.add(ZeroOrderHoldDirect(sample_time=0.02, x0=7.5, id="zohd"))
    sim.connect(src, "zohd")
    path = tmp_path / "zohd.json"
    sim.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    sim_loaded = Simulator.load(path)
    return data, sim_loaded


def test_zero_order_hold_direct_json_roundtrip_type_string(_zohd_persisted) -> None:
    """save/load で ZOHDirect の type 文字列が 'flode.blocks.discrete.ZeroOrderHoldDirect' になる。"""
    data, _ = _zohd_persisted
    zohd_entry = next(b for b in data["blocks"] if b["id"] == "zohd")
    assert zohd_entry["type"] == "flode.blocks.discrete.ZeroOrderHoldDirect"


def test_zero_order_hold_direct_json_roundtrip_sample_time(_zohd_persisted) -> None:
    """save/load で ZOHDirect の sample_time が正確に往復する。"""
    _, sim_loaded = _zohd_persisted
    zohd2 = sim_loaded.get_block("zohd")
    assert zohd2.sample_time == pytest.approx(0.02)


def test_zero_order_hold_direct_json_roundtrip_x0(_zohd_persisted) -> None:
    """save/load で ZOHDirect の x0 が正確に往復する。"""
    _, sim_loaded = _zohd_persisted
    zohd2 = sim_loaded.get_block("zohd")
    np.testing.assert_allclose(zohd2.x0, [7.5])


def test_zero_order_hold_direct_json_roundtrip_run_produces_same_output() -> None:
    """load 後に run() した結果が save 前と同じ出力になる。"""

    def _run(sample_time: float, x0: float) -> np.ndarray:
        sim = Simulator(t_end=0.04, dt=0.01)
        src = sim.add(Constant(value=3.0, id="src"))
        zohd = sim.add(ZeroOrderHoldDirect(sample_time=sample_time, x0=x0, id="zohd"))
        sc = sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(src, zohd)
        sim.connect(zohd, sc)
        sim.run()
        return _flat(sc)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    try:
        sim_orig = Simulator(t_end=0.04, dt=0.01)
        src = sim_orig.add(Constant(value=3.0, id="src"))
        zohd = sim_orig.add(ZeroOrderHoldDirect(sample_time=0.01, x0=0.0, id="zohd"))
        sc_orig = sim_orig.add(Scope(n_inputs=1, id="sc"))
        sim_orig.connect(src, zohd)
        sim_orig.connect(zohd, sc_orig)
        sim_orig.run()
        orig_arr = _flat(sc_orig)

        sim_orig.save(path)
        sim_loaded = Simulator.load(path)
        sc_loaded = sim_loaded.get_block("sc")
        sim_loaded.run()
        loaded_arr = _flat(sc_loaded)

        np.testing.assert_allclose(loaded_arr, orig_arr, atol=1e-12)
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. sample_time 不正値バリデーション (Block.__init__ の検証)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_st",
    [
        -0.001,  # -1.0 以外の負数
        -2.0,
        -100.0,
    ],
)
def test_zero_order_hold_direct_invalid_negative_sample_time_raises(
    invalid_st: float,
) -> None:
    """sample_time が -1.0 以外の負数なら BlockSpecError が発生する。"""
    with pytest.raises(BlockSpecError, match="sample_time"):
        ZeroOrderHoldDirect(sample_time=invalid_st)


@pytest.mark.parametrize(
    "invalid_st",
    [
        -0.001,
        -2.0,
    ],
)
def test_unit_delay_invalid_negative_sample_time_raises(invalid_st: float) -> None:
    """UnitDelay でも -1.0 以外の負数で BlockSpecError が発生する (Block 基底の検証)。"""
    with pytest.raises(BlockSpecError, match="sample_time"):
        UnitDelay(sample_time=invalid_st)


def test_zero_order_hold_direct_sample_time_minus_one_is_valid() -> None:
    """sample_time=-1.0 (継承) は有効な値としてインスタンス生成できる。"""
    zohd = ZeroOrderHoldDirect(sample_time=-1.0)
    assert zohd.sample_time == -1.0


# ---------------------------------------------------------------------------
# 3. sample_time=-1.0 継承: 上流離散→解決、上流連続→連続扱い (ADR-0002 §(2))
# ---------------------------------------------------------------------------


def test_zero_order_hold_direct_inherits_sample_time_from_discrete_upstream() -> None:
    """sample_time=-1.0 のとき、上流離散ブロックの sample_time を継承する。"""
    sim = Simulator(t_end=0.06, dt=0.01)
    src = sim.add(Constant(value=1.0))
    ud_upstream = sim.add(UnitDelay(sample_time=0.02, x0=0.0))
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=-1.0, id="zohd"))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, ud_upstream)
    sim.connect(ud_upstream, zohd)
    sim.connect(zohd, sc)
    sim.run()

    # _resolve_sample_times が上流 (sample_time=0.02) を継承する
    assert zohd._resolved_sample_time == pytest.approx(0.02)


def test_zero_order_hold_direct_inherits_sample_time_output_correct() -> None:
    """sample_time=-1.0 継承後、ZOHDirect は継承した周期で正しく動作する。

    DiscreteIntegrator (sample_time=0.02) → ZOHDirect (-1.0 継承) の構成で、
    ZOHDirect が 0.02 を継承し、サンプル時刻 0, 0.02, 0.04, ... で上流値を
    即時反映、中間時刻でホールドすることを確認する。

    DiscreteIntegrator は constant input=1, gain=1, T=0.02 で
    x[k+1] = x[k] + 0.02、x[0]=0、x[1]=0.02、x[2]=0.04、...
    """
    sim = Simulator(t_end=0.06, dt=0.01)
    src = sim.add(Constant(value=1.0))
    di_upstream = sim.add(DiscreteIntegrator(sample_time=0.02, gain=1.0, x0=0.0, id="di"))
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=-1.0, id="zohd"))
    sc = sim.add(Scope(n_inputs=1, id="sc_zohd"))
    sim.connect(src, di_upstream)
    sim.connect(di_upstream, zohd)
    sim.connect(zohd, sc)
    sim.run()

    # 継承確認
    assert zohd._resolved_sample_time == pytest.approx(0.02)
    arr = _flat(sc)
    times = np.array(sc.times)
    # ZOHDirect 自身のサンプル時刻 (0, 0.02, 0.04, 0.06) では上流 DI の現出力を反映。
    # DI 出力 (sample_time=0.02、step_ratio=2 で fire at k=1, 3, 5):
    # - k=0 (t=0): DI x=0
    # - k=1 (t=0.01): DI [A] x=0、[A'] update: x_new = 0 + 0.02*1 = 0.02
    # - k=2 (t=0.02): DI x=0.02 → ZOHDirect サンプル時刻、output=0.02
    # - k=3 (t=0.03): DI x=0.02、[A'] update: x_new = 0.04
    # - k=4 (t=0.04): DI x=0.04 → ZOHDirect サンプル時刻、output=0.04
    # - k=5 (t=0.05): DI x=0.04
    # - k=6 (t=0.06): DI x=0.06 → ZOHDirect サンプル時刻、output=0.06
    expected_at_sample_times = {0.0: 0.0, 0.02: 0.02, 0.04: 0.04, 0.06: 0.06}
    for t_target, expected in expected_at_sample_times.items():
        idx = int(np.argmin(np.abs(times - t_target)))
        assert arr[idx] == pytest.approx(expected, abs=1e-12)


def test_zero_order_hold_direct_inherits_continuous_upstream_falls_back_to_dt() -> None:
    """sample_time=-1.0 で上流が連続ブロック (Integrator) なら dt にフォールバックする。

    ADR-0002 §(2) 改訂 (v0.57.0): 離散専用ブロック (requires_discrete_rate=True)
    は上流に離散レートがないとき dt を採用する。旧仕様 (None = 連続扱いの実質
    パススルー) から挙動変更 — dt 周期で実際に hold する方が有用なため。
    """
    from flode.blocks.continuous import Integrator

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    integ = sim.add(Integrator(x0=0.0))
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=-1.0, id="zohd"))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, integ)
    sim.connect(integ, zohd)
    sim.connect(zohd, sc)
    sim.run()

    # 上流に離散レートなし → dt にフォールバック (連続扱いにしない)
    assert zohd._resolved_sample_time == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# 4. ZOHDirect 浮動小数サンプル時刻判定の境界値
# ---------------------------------------------------------------------------


def test_zero_order_hold_direct_sample_time_boundary_at_t0() -> None:
    """t=0 はサンプル時刻として正しく判定され、x0 ではなく u(0) が返る。

    境界: abs(0 - 0*ts) = 0 <= tol*max(1,0) = tol → True (サンプル時刻判定成功)。
    """
    sim = Simulator(t_end=0.02, dt=0.01)
    src = sim.add(Constant(value=42.0))
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=0.01, x0=77.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, zohd)
    sim.connect(zohd, sc)
    sim.run()

    arr = _flat(sc)
    # t=0 でも x0=77 ではなく u(0)=42 が即時反映される
    assert arr[0] == pytest.approx(42.0)


def test_zero_order_hold_direct_large_t_sample_time_boundary() -> None:
    """大きな t (t=1.0) でも浮動小数サンプル時刻判定が正しく機能する。

    tol = 1e-9 * max(1, |t|) スケールで誤判定が起きないことを確認する。
    """
    dt = 0.01
    t_end = 1.0
    sim = Simulator(t_end=t_end, dt=dt)
    clk = sim.add(Clock())
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=dt))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, zohd)
    sim.connect(zohd, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    # ZOHDirect は各サンプル時刻で Clock 出力 (= t) を即時反映するので
    # 出力は Clock と一致するはず
    np.testing.assert_allclose(arr, times, atol=1e-9)


def test_zero_order_hold_direct_x0_irrelevant_at_t0_sample_time() -> None:
    """複数の x0 値で ZOHDirect の出力が t=0 サンプル時刻で同一になる。

    x0=0 と x0=999 の場合でも、sample_time=dt_base なら t=0 で即時反映により同じ出力。
    """

    def run_with_x0(x0_val: float) -> np.ndarray:
        sim = Simulator(t_end=0.03, dt=0.01)
        src = sim.add(Constant(value=5.0))
        zohd = sim.add(ZeroOrderHoldDirect(sample_time=0.01, x0=x0_val))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, zohd)
        sim.connect(zohd, sc)
        sim.run()
        return _flat(sc)

    arr_a = run_with_x0(0.0)
    arr_b = run_with_x0(999.0)
    np.testing.assert_array_equal(arr_a, arr_b)


# ---------------------------------------------------------------------------
# 7. Subsystem 内の離散ブロックが ADR-0014 semantics に従うこと (Risks #6)
# ---------------------------------------------------------------------------


def test_subsystem_inner_unit_delay_one_sample_delay() -> None:
    """Subsystem 内の UnitDelay が ADR-0014 semantics (y[k+1]=u[k]) に従う。

    外側 Simulator の run() ループが Subsystem の update() を [A'] で呼び、
    UnitDelay の状態が正しく 1 サンプル遅延することを確認する (ADR-0014 Risks #6)。
    """
    from flode.subsystems import Subsystem
    from flode.subsystems.ports import Inport, Outport

    sub = Subsystem(id="sub")
    inp = sub.add(Inport(port_idx=0, id="inp"))
    ud = sub.add(UnitDelay(sample_time=0.01, x0=99.0, id="ud_inner"))
    outp = sub.add(Outport(port_idx=0, id="outp"))
    sub.connect(inp, ud)
    sub.connect(ud, outp)

    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock(id="clk"))
    s = sim.add(sub)
    sc = sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect(clk, s)
    sim.connect(s, sc)
    sim.run()

    arr = _flat(sc)
    # UnitDelay(x0=99, u=Clock): y[0]=99, y[1]=0, y[2]=0.01, y[3]=0.02, ...
    expected = np.array([99.0, 0.00, 0.01, 0.02, 0.03, 0.04])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_subsystem_inner_discrete_integrator_resolved_sample_time_not_propagated() -> None:
    """Subsystem 内の DiscreteIntegrator には外側の _resolve_sample_times が伝播しない。

    既知の実装制限 (ADR-0014 Risks #6): Subsystem 内部ブロックは外側 Simulator の
    _resolve_sample_times に含まれないため、DiscreteIntegrator が使う
    _resolved_sample_time が None のまま update() で BlockSpecError が発生する。
    UnitDelay は _resolved_sample_time を使わないため影響を受けない。

    これは Phase 3 で Subsystem と外部スケジューラの統合を再設計する際に修正予定
    (subsystem.py: code-reviewer MUST #1 参照)。
    """
    from flode.subsystems import Subsystem
    from flode.subsystems.ports import Inport, Outport

    sub = Subsystem(id="sub")
    inp = sub.add(Inport(port_idx=0, id="inp"))
    di = sub.add(DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0, id="di_inner"))
    outp = sub.add(Outport(port_idx=0, id="outp"))
    sub.connect(inp, di)
    sub.connect(di, outp)

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    s = sim.add(sub)
    sc = sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect(src, s)
    sim.connect(s, sc)

    # 既知制限: DiscreteIntegrator の _resolved_sample_time が None のまま
    # update() 内で BlockSpecError が発生する
    with pytest.raises(BlockSpecError, match="sample_time has not been resolved"):
        sim.run()


# ---------------------------------------------------------------------------
# 8. on_step_callback のタイミング (ADR-0011 §(4))
# ---------------------------------------------------------------------------


def test_on_step_callback_called_after_record_not_before() -> None:
    """on_step_callback が record の直後に呼ばれる: callback 時刻 == scope.times[-1]。

    ループ順序 [A]→[E]record→callback→[A']update→[B]integrate に従い、
    callback 内で参照できる scope の最後のサンプル時刻が callback の t と一致する。
    """
    callback_scope_last_times: list[tuple[float, float]] = []

    sim = Simulator(t_end=0.03, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)

    def callback(t: float, t_end: float) -> bool:
        last_t = sc.times[-1] if sc.times else float("nan")
        callback_scope_last_times.append((t, last_t))
        return True

    sim.on_step_callback = callback
    sim.run()

    for cb_t, sc_last_t in callback_scope_last_times:
        assert cb_t == pytest.approx(sc_last_t, abs=1e-12), (
            f"callback(t={cb_t}) but scope.times[-1]={sc_last_t}: "
            "callback should be called after record"
        )


def test_on_step_callback_false_stops_before_update() -> None:
    """callback が False を返した後、update は実行されず次ステップは記録されない。

    t=0.02 で False を返すと:
    - scope には t=0, 0.01, 0.02 が記録される (record は [E] で完了)
    - t=0.03 以降は記録されない (update/integrate/次ループが実行されない)
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)

    def callback(t: float, t_end: float) -> bool:
        if t >= 0.02:
            return False
        return True

    sim.on_step_callback = callback
    sim.run()

    # record までは完了しているので t=0,0.01,0.02 の 3 点が残る
    assert sc.times == pytest.approx([0.0, 0.01, 0.02])
    # t=0.03 以降は記録されない
    assert len(sc.times) == 3


# ---------------------------------------------------------------------------
# 9. request_stop() graceful stop (ADR-0011 §(4))
# ---------------------------------------------------------------------------


def test_request_stop_preserves_records_up_to_stop_point() -> None:
    """request_stop() が呼ばれた時刻まで record が保存される。

    ループ内で request_stop() → [E] は完了済み → [A'] は実行されずに return。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)

    def callback(t: float, t_end: float) -> bool:
        if t >= 0.02:
            sim.request_stop()
        return True

    sim.on_step_callback = callback
    sim.run()

    # request_stop 後のチェックで return → t=0.02 まで record される
    assert sc.times[-1] == pytest.approx(0.02)
    assert sim.is_stopped is True


def test_request_stop_marks_is_stopped_flag() -> None:
    """request_stop() 後に is_stopped が True になる。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)

    def callback(t: float, t_end: float) -> bool:
        sim.request_stop()
        return True

    sim.on_step_callback = callback
    sim.run()

    assert sim.is_stopped is True


def test_request_stop_clears_flag_on_rerun() -> None:
    """run() を再実行すると _stop_requested フラグがリセットされる。"""
    sim = Simulator(t_end=0.02, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)

    # 1 回目: 即 stop
    call_count = [0]

    def callback_first(t: float, t_end: float) -> bool:
        call_count[0] += 1
        if call_count[0] >= 1:
            sim.request_stop()
        return True

    sim.on_step_callback = callback_first
    sim.run()
    assert sim.is_stopped is True

    # 2 回目: コールバックなし → フルランが完了し is_stopped=False
    sim.on_step_callback = None
    sim.run()
    assert sim.is_stopped is False
    # n_steps+1 点が記録される (t=0, 0.01, 0.02)
    assert len(sc.times) == 3


# ---------------------------------------------------------------------------
# 10. DiscreteIntegrator with Sine 入力 (前進 Euler 精密確認)
# ---------------------------------------------------------------------------


def test_discrete_integrator_sine_input_forward_euler() -> None:
    """DiscreteIntegrator with Sine 入力の前進 Euler 精密確認。

    u(t) = sin(2π t), gain=1, T=0.01:
    x[k+1] = x[k] + T * sin(2π * t_k)
    解析的な累積和と一致することを確認する。
    """
    from flode.blocks import Sine

    T = 0.01
    n = 5
    t_end = n * T
    sim = Simulator(t_end=t_end, dt=T)
    sine = sim.add(Sine(amplitude=1.0, frequency=1.0))
    di = sim.add(DiscreteIntegrator(sample_time=T, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(sine, di)
    sim.connect(di, sc)
    sim.run()

    arr = _flat(sc)
    # 期待値: x[k] = sum_{i=0}^{k-1} T * sin(2π * i*T)
    expected = np.zeros(n + 1)
    for k in range(1, n + 1):
        expected[k] = expected[k - 1] + T * np.sin(2 * np.pi * (k - 1) * T)
    np.testing.assert_allclose(arr, expected, atol=1e-12)


# ---------------------------------------------------------------------------
# 11. DiscreteStateSpace 2 次安定系 (multi-dimensional standard form)
# ---------------------------------------------------------------------------


def test_discrete_state_space_2nd_order_stable() -> None:
    """2 次安定系 DiscreteStateSpace が x[k+1]=Ax[k]+Bu[k] 標準形に従う。

    A=[[0,1],[-0.5,-0.5]] (|λ|=1/√2 < 1 で安定), B=[[0],[1]], C=[[1,0]], D=[[0]].
    定数入力 u[k]=1 で数値解と解析解が一致することを確認する。
    """
    A = np.array([[0.0, 1.0], [-0.5, -0.5]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0]])
    D = np.array([[0.0]])

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dss = sim.add(
        DiscreteStateSpace(
            A=A,
            B=B,
            C=C,
            D=D,
            sample_time=0.01,
            x0=np.array([0.0, 0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dss)
    sim.connect(dss, sc)
    sim.run()

    arr = _flat(sc)

    # 解析解: y[k] = C x[k], x[k+1] = A x[k] + B u[k]
    x = np.zeros(2)
    expected = []
    for _ in range(6):
        y = float((C @ x).ravel()[0])
        expected.append(y)
        x = A @ x + B.ravel() * 1.0

    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_discrete_state_space_2nd_order_eigenvalues_inside_unit_circle() -> None:
    """2 次安定系の固有値が単位円内にあることの事前確認 (設計整合性テスト)。"""
    A = np.array([[0.0, 1.0], [-0.5, -0.5]])
    eigs = np.linalg.eigvals(A)
    assert np.all(np.abs(eigs) < 1.0), f"Eigenvalues {eigs} should all be inside unit circle"


# ---------------------------------------------------------------------------
# 12. DiscreteTransferFunction 2 次 (高次標準形)
# ---------------------------------------------------------------------------


def test_discrete_transfer_function_2nd_order_standard_form() -> None:
    """2 次 DiscreteTransferFunction H(z)=1/(z^2-0.5z) の標準形確認。

    H(z) = 1/(z^2 - 0.5z): 定数入力 u[k]=1 での標準形 x[k+1]=Ax[k]+Bu[k] と
    一致することを、解析計算と比較して確認する。
    """
    # H(z) = 1/(z^2 - 0.5z + 0) → 分母 [1, -0.5, 0]
    num = [1.0]
    den = [1.0, -0.5, 0.0]

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dtf = sim.add(
        DiscreteTransferFunction(
            numerator=num,
            denominator=den,
            sample_time=0.01,
            x0=np.array([0.0, 0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dtf)
    sim.connect(dtf, sc)
    sim.run()

    arr = _flat(sc)
    # scipy.signal.tf2ss 経由の内部 SS 表現に従う解析解
    import scipy.signal

    A_ss, B_ss, C_ss, D_ss = scipy.signal.tf2ss(np.array(num), np.array(den))
    x = np.zeros(A_ss.shape[0])
    expected = []
    for _ in range(6):
        y = float((C_ss @ x + D_ss.ravel() * 1.0).ravel()[0])
        expected.append(y)
        x = A_ss @ x + B_ss.ravel() * 1.0

    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_discrete_transfer_function_2nd_order_n_states() -> None:
    """2 次 DTF が n_states=4 のブロックとして構築される。

    ADR-0015 §(3) で 2n-state augmentation を導入: 内部 SS 表現の n=2 に対し
    augmented state は 2n=4。``output_curr`` (2 要素) + ``next_x`` (2 要素)。
    """
    dtf = DiscreteTransferFunction(
        numerator=[1.0],
        denominator=[1.0, -0.5, 0.0],
        sample_time=0.01,
    )
    # ADR-0015: n_states = 2 * (deg(den)) = 2 * 2 = 4
    assert dtf.n_states == 4


# ---------------------------------------------------------------------------
# 13. multi-rate UnitDelay の off-by-one 既知制限の定量化 (ADR-0014 §Risks #1)
# ---------------------------------------------------------------------------


def test_multirate_unit_delay_reference_semantics() -> None:
    """multi-rate (sample_time > dt_base) での UnitDelay が真の reference semantics に従う。

    ADR-0015 で根本治療済み: ADR-0014 で known limitation として残っていた
    「multi-rate で 1 dt_base off-by-one」が、2-state augmentation + fire timing
    変更で解消された。

    sample_time=0.1, dt_base=0.01, x0=0, Clock 入力 u(t)=t で:
    - y(t in [0, 0.1)) = x0 = 0
    - y(t in [0.1, 0.2)) = u(0) = 0
    - y(t in [0.2, 0.3)) = u(0.1) = 0.1
    - y(t in [0.3, 0.4)) = u(0.2) = 0.2
    """
    dt_base = 0.01
    sample_time = 0.1
    t_end = 0.5

    sim = Simulator(t_end=t_end, dt=dt_base)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=sample_time, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)

    # サンプル時刻 (step_ratio=10) のインデックスを抽出
    sample_indices = [
        i for i, t in enumerate(times) if abs(round(t / sample_time) * sample_time - t) < 1e-9
    ]

    y_at_sample_times = arr[sample_indices]
    sample_times_actual = times[sample_indices]

    # y(0) = x0 = 0
    assert sample_times_actual[0] == pytest.approx(0.0)
    assert y_at_sample_times[0] == pytest.approx(0.0)

    # y(0.1) = u(0) = 0 (1 サンプル遅延、reference semantics)
    assert sample_times_actual[1] == pytest.approx(0.1)
    assert y_at_sample_times[1] == pytest.approx(0.0, abs=1e-10)

    # y(0.2) = u(0.1) = 0.1
    assert sample_times_actual[2] == pytest.approx(0.2)
    assert y_at_sample_times[2] == pytest.approx(0.1, abs=1e-10)

    # y(0.3) = u(0.2) = 0.2
    assert sample_times_actual[3] == pytest.approx(0.3)
    assert y_at_sample_times[3] == pytest.approx(0.2, abs=1e-10)


def test_multirate_unit_delay_systematic_semantics() -> None:
    """multi-rate UnitDelay が全サンプル時刻で y(t_n) = u(t_{n-1}) (reference semantics) に従う。

    ADR-0015 適用後:
    - y(t in [n*T, (n+1)*T)) = u((n-1)*T) for n >= 1
    - y(t in [0, T)) = x0
    """
    dt_base = 0.01
    sample_time = 0.1
    t_end = 0.5

    sim = Simulator(t_end=t_end, dt=dt_base)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=sample_time, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_indices = [
        i for i, t in enumerate(times) if abs(round(t / sample_time) * sample_time - t) < 1e-9
    ]
    y_at_sample = arr[sample_indices]
    t_at_sample = times[sample_indices]

    # 各サンプル時刻 t_n (n >= 1) で y(t_n) = u(t_{n-1}) = t_n - sample_time
    for i in range(1, len(sample_indices)):
        t_n = t_at_sample[i]
        expected_reference = t_n - sample_time  # u(t_{n-1}) = t_n - sample_time
        assert y_at_sample[i] == pytest.approx(expected_reference, abs=1e-10), (
            f"t={t_n:.2f}: y_flode={y_at_sample[i]}, expected_reference={expected_reference}"
        )
