"""複雑怪奇ハイブリッドモデル (非線形振り子 + 多段離散制御) の挙動検証。

flode のスケジューラ・Subsystem (入れ子)・Trigger/Enable・Goto/From・Mux/Demux・
離散ブロック群・むだ時間・ヒステリシス・レートリミッタ・ルックアップ・
ユーザ関数を 1 つの閉ループに詰め込み、以下 5 種類の **独立した参照** と
突き合わせる。

1. ``hybrid``:    同じ方程式を手書きした平文 numpy/scipy 実装 (flode の
                  update-before-output 実行順序を模した参照) と全信号を比較
2. ``roundtrip``: ``save()`` → ``load()`` → ``run()`` で bit 一致
3. ``linearize``: 振り子 Subsystem の線形化 A 行列を解析解と比較 (θ=0 / θ=π)
4. ``pendulum``:  非減衰・無入力の振り子でエネルギー保存と楕円積分による厳密周期
5. ``dde``:       遅延微分方程式 x'(t) = -x(t-1) を TransportDelay で組み、
                  (a) flode が実際に解いている差分漸化式と機械精度で一致するか、
                  (b) 段階法による厳密解と O(dt) で一致するかを確認

実行::

    venv/Scripts/python.exe src/examples/hybrid_torture_verification.py
"""

from __future__ import annotations

import logging
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy.integrate import solve_ivp
from scipy.special import ellipk

from flode import Enable, Inport, Outport, Simulator, Subsystem, Trigger
from flode.blocks import (
    Abs,
    Clock,
    Constant,
    Demux,
    DiscreteTransferFunction,
    Divide,
    Fcn,
    From,
    Gain,
    Goto,
    Integrator,
    LogicalOperator,
    LookupTable1D,
    MathFunction,
    MultiportSwitch,
    Mux,
    Product,
    PulseGenerator,
    RateLimiter,
    Relay,
    Rounding,
    Saturation,
    Scope,
    Sign,
    Sine,
    Step,
    Sum,
    Switch,
    TransportDelay,
    TrigFunction,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パラメータ
# ---------------------------------------------------------------------------
M, L, G = 0.8, 0.6, 9.81  # 質量 [kg]、腕長 [m]、重力加速度
C_DAMP = 0.15  # 粘性減衰トルク係数 [N m s/rad]
J = M * L * L  # 慣性モーメント
MGL = M * G * L  # 重力トルク係数
THETA0 = 0.3  # 初期角 [rad]

DT = 0.005  # 基準ステップ
TS_CTRL = 0.05  # 制御器サンプル周期
TS_SENSOR = 0.01  # センサ (むだ時間) サンプル周期
DELAY = 0.1  # センサむだ時間
T_END = 12.0

KP_BP = (0.0, 0.3, 1.0)  # ゲインスケジュール breakpoints (|e|)
KP_TBL = (6.0, 9.0, 12.0)
KI, KD = 4.0, 0.8
U_MAX = 4.0
SLEW = 20.0
BB_LEVEL = 3.0  # bang-bang トルク
RELAY_ON, RELAY_OFF = 0.6, 0.3  # |e| によるモード切替ヒステリシス

STEP_TIME, STEP_VALUE = 1.0, 0.8
R_SINE_AMP, R_SINE_FREQ = 0.2, 0.15
PULSE_PERIOD = 0.5
DIST_SINE_AMP, DIST_SINE_FREQ, DIST_CONST = 0.5, 0.4, 0.6
DIST_SLOT = 3.0  # 外乱プロファイルを 3 s ごとに切替

RTOL, ATOL = 1e-8, 1e-11  # hybrid チェックの solve_ivp 許容誤差 (flode と参照で共有)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# モデル構築 (flode)
# ---------------------------------------------------------------------------
def build_pendulum_subsystem(
    c: float, theta0: float, *, id: str = "plant", nested: bool = True
) -> Subsystem:
    """非線形振り子 J θ'' = τ - c θ' - m g L sin θ を Subsystem で組む。

    ``nested=True`` なら重力トルク項を入れ子 Subsystem ``gravity`` に分離する
    (2 階層)。``False`` なら同じブロックを平坦に置く (浮動小数演算は同一なので
    両者の実行結果は bit 一致するはず)。除算は ``Divide``、加算は
    ``Sum("+--")``。入力 0 = τ、出力 0 = θ、出力 1 = ω。
    """
    plant = Subsystem(id=id)
    plant.add(Inport(port_idx=0, id="tau_in"))
    plant.add(Sum(signs="+--", id="net"))
    plant.add(Constant(value=J, id="J"))
    plant.add(Divide(signs="*/", id="alpha"))
    plant.add(Integrator(x0=0.0, id="omega"))
    plant.add(Integrator(x0=theta0, id="theta"))
    plant.add(Gain(k=c, id="damp"))
    plant.add(Outport(port_idx=0, id="th_out"))
    plant.add(Outport(port_idx=1, id="om_out"))
    if nested:
        grav = Subsystem(id="gravity")
        grav.add(Inport(port_idx=0, id="th_in"))
        grav.add(TrigFunction("sin", id="sin"))
        grav.add(Gain(k=MGL, id="mgl"))
        grav.add(Outport(port_idx=0, id="tq_out"))
        grav.connect("th_in", "sin")
        grav.connect("sin", "mgl")
        grav.connect("mgl", "tq_out")
        plant.add(grav)
        plant.connect("gravity", "net", dst_idx=2)
    else:
        plant.add(TrigFunction("sin", id="sin"))
        plant.add(Gain(k=MGL, id="gravity"))
        plant.connect("theta", "sin")
        plant.connect("sin", "gravity")
        plant.connect("gravity", "net", dst_idx=2)
    plant.connect("tau_in", "net", dst_idx=0)
    plant.connect("damp", "net", dst_idx=1)
    plant.connect("net", "alpha", dst_idx=0)
    plant.connect("J", "alpha", dst_idx=1)
    plant.connect("alpha", "omega")
    plant.connect("omega", "theta")
    plant.connect("omega", "damp")
    if nested:
        plant.connect("theta", "gravity")
    plant.connect("theta", "th_out")
    plant.connect("omega", "om_out")
    return plant


def build_hybrid_model(*, nested: bool = True) -> tuple[Simulator, Scope]:
    """複雑怪奇ハイブリッド閉ループを構築する。

    信号の流れ::

        r_raw = Step + Sine ──▶ [Triggered S/H (PulseGenerator 立上りで更新)] = r_sh
        θ ──Goto/From──▶ TransportDelay(0.1 s, Ts=0.01) = y_del
        e = r_sh − y_del
        |e| ──▶ Relay(ヒステリシス, Ts=0.05) = mode (1: bang-bang, 0: PID)
        u_bb  = 3·sign(e)
        u_pid = LUT(|e|)·e + KI·I + KD·DTF(y_del)      I: Enabled 積分器 (mode=0 の間のみ)
        u     = Switch(mode) → Saturation(±4) → RateLimiter(±20/s, Ts=0.05) = τ
        d(t)  = MultiportSwitch(floor(t/3) mod 3) ∈ {0, 0.5 sin, 0.6}
        plant: J θ'' = τ + d − c θ' − m g L sin θ  (入れ子 Subsystem)
        Mux(θ, ω) → Demux → Scope、Fcn でエネルギー
    """
    sim = Simulator(t_end=T_END, dt=DT, rtol=RTOL, atol=ATOL)

    # --- 目標値 + サンプル&ホールド (Triggered Subsystem) ---
    sim.add(Step(step_time=STEP_TIME, initial_value=0.0, final_value=STEP_VALUE, id="step"))
    sim.add(Sine(amplitude=R_SINE_AMP, frequency=R_SINE_FREQ, id="r_sine"))
    sim.add(Sum(signs="++", id="r_raw"))
    sim.add(PulseGenerator(period=PULSE_PERIOD, pulse_width=50.0, id="pulse"))
    sh = Subsystem(id="sh")
    sh.add(Inport(port_idx=0, id="in"))
    sh.add(Outport(port_idx=0, id="out"))
    sh.add(Trigger(trigger_type="rising", id="trig"))
    # 状態を持たない Triggered Subsystem は基準クロック (dt) で edge 判定される
    # (2026-09-13 bug-fix 以前は update() が呼ばれず発火しなかった)
    sh.connect("in", "out")
    sim.add(sh)
    sim.connect("step", "r_raw", dst_idx=0)
    sim.connect("r_sine", "r_raw", dst_idx=1)
    sim.connect("r_raw", "sh", dst_idx=0)
    sim.connect("pulse", "sh", dst_idx=1)

    # --- プラント + 仮想配線 ---
    sim.add(build_pendulum_subsystem(C_DAMP, THETA0, nested=nested))
    sim.add(Goto(tag="theta", id="goto_theta"))
    sim.add(From(tag="theta", id="from_theta_sensor"))
    sim.add(From(tag="theta", id="from_theta_energy"))
    sim.connect("plant", "goto_theta", src_idx=0)

    # --- センサむだ時間と偏差 ---
    sim.add(TransportDelay(delay_time=DELAY, sample_time=TS_SENSOR, id="sensor"))
    sim.add(Sum(signs="+-", id="err"))
    sim.add(Abs(id="abs_e"))
    sim.connect("from_theta_sensor", "sensor")
    sim.connect("sh", "err", dst_idx=0)
    sim.connect("sensor", "err", dst_idx=1)
    sim.connect("err", "abs_e")

    # --- モード切替 (Relay) と bang-bang ---
    sim.add(
        Relay(
            sample_time=TS_CTRL,
            switch_on_point=RELAY_ON,
            switch_off_point=RELAY_OFF,
            id="mode",
        )
    )
    sim.add(Sign(id="sign_e"))
    sim.add(Gain(k=BB_LEVEL, id="u_bb"))
    sim.connect("abs_e", "mode")
    sim.connect("err", "sign_e")
    sim.connect("sign_e", "u_bb")

    # --- PID (ゲインスケジュール P + Enabled 積分 I + 離散フィルタ D) ---
    sim.add(LookupTable1D(breakpoints=KP_BP, table=KP_TBL, id="kp_lut"))
    sim.add(Product(n_inputs=2, id="p_term"))
    sim.add(LogicalOperator(operator="NOT", n_inputs=1, id="not_mode"))
    aw = Subsystem(id="aw_int")
    aw.add(Inport(port_idx=0, id="e_in"))
    aw.add(Integrator(x0=0.0, id="I"))
    aw.add(Outport(port_idx=0, id="I_out"))
    aw.add(Enable(states_when_enabling="held", outputs_when_disabled="held", id="en"))
    aw.connect("e_in", "I")
    # 内部が Integrator のみ (非直達) でも enable ポートは output() 時点で読まれる
    # (2026-09-13 bug-fix 以前は enable が常に 0 と読まれ出力が凍結していた)
    aw.connect("I", "I_out")
    sim.add(aw)
    sim.add(Gain(k=KI, id="i_term"))
    sim.add(
        DiscreteTransferFunction(
            numerator=[1.0, -1.0],
            denominator=[TS_CTRL, -0.5 * TS_CTRL, 0.0],
            sample_time=TS_CTRL,
            id="dfilt",
        )
    )
    sim.add(Gain(k=KD, id="d_term"))
    sim.add(Sum(signs="+++", id="u_pid"))
    sim.connect("abs_e", "kp_lut")
    sim.connect("kp_lut", "p_term", dst_idx=0)
    sim.connect("err", "p_term", dst_idx=1)
    sim.connect("mode", "not_mode")
    sim.connect("err", "aw_int", dst_idx=0)
    sim.connect("not_mode", "aw_int", dst_idx=1)
    sim.connect("aw_int", "i_term")
    sim.connect("sensor", "dfilt")
    sim.connect("dfilt", "d_term")
    sim.connect("p_term", "u_pid", dst_idx=0)
    sim.connect("i_term", "u_pid", dst_idx=1)
    sim.connect("d_term", "u_pid", dst_idx=2)

    # --- 選択 → 飽和 → レートリミッタ ---
    sim.add(Switch(threshold=0.5, criterion=">=", id="sw"))
    sim.add(Saturation(lower=-U_MAX, upper=U_MAX, id="sat"))
    sim.add(
        RateLimiter(sample_time=TS_CTRL, rising_slew_rate=SLEW, falling_slew_rate=-SLEW, id="rl")
    )
    sim.connect("u_bb", "sw", dst_idx=0)
    sim.connect("mode", "sw", dst_idx=1)
    sim.connect("u_pid", "sw", dst_idx=2)
    sim.connect("sw", "sat")
    sim.connect("sat", "rl")

    # --- 外乱プロファイル (Clock → floor → mod → MultiportSwitch) ---
    sim.add(Clock(id="clk"))
    sim.add(Gain(k=1.0 / DIST_SLOT, id="slot"))
    sim.add(Rounding(mode="floor", id="floor"))
    sim.add(Constant(value=3.0, id="three"))
    sim.add(MathFunction(function="mod", id="mod3"))
    sim.add(Constant(value=0.0, id="d_zero"))
    sim.add(Sine(amplitude=DIST_SINE_AMP, frequency=DIST_SINE_FREQ, id="d_sine"))
    sim.add(Constant(value=DIST_CONST, id="d_const"))
    sim.add(MultiportSwitch(n_choices=3, index_base="zero", id="d_sel"))
    sim.add(Sum(signs="++", id="tau_total"))
    sim.connect("clk", "slot")
    sim.connect("slot", "floor")
    sim.connect("floor", "mod3", dst_idx=0)
    sim.connect("three", "mod3", dst_idx=1)
    sim.connect("mod3", "d_sel", dst_idx=0)
    sim.connect("d_zero", "d_sel", dst_idx=1)
    sim.connect("d_sine", "d_sel", dst_idx=2)
    sim.connect("d_const", "d_sel", dst_idx=3)
    sim.connect("rl", "tau_total", dst_idx=0)
    sim.connect("d_sel", "tau_total", dst_idx=1)
    sim.connect("tau_total", "plant")

    # --- 観測: Mux/Demux 経由 + エネルギー Fcn ---
    sim.add(Mux(n=2, id="mux"))
    sim.add(Demux(n=2, id="demux"))
    sim.add(
        Fcn(
            expression=f"{0.5 * J!r}*u[1]**2 + {MGL!r}*(1-cos(u[0]))",
            n_inputs=2,
            id="energy",
        )
    )
    labels = ["theta", "omega", "tau", "mode", "r_sh", "e", "u_pid", "energy"]
    scope = Scope(n_inputs=len(labels), labels=labels, buffer_mode="unbounded", id="scope")
    sim.add(scope)
    sim.connect("plant", "mux", src_idx=0, dst_idx=0)
    sim.connect("plant", "mux", src_idx=1, dst_idx=1)
    sim.connect("mux", "demux")
    sim.connect("from_theta_energy", "energy", dst_idx=0)
    sim.connect("plant", "energy", src_idx=1, dst_idx=1)
    sim.connect("demux", "scope", src_idx=0, dst_idx=0)
    sim.connect("demux", "scope", src_idx=1, dst_idx=1)
    sim.connect("rl", "scope", dst_idx=2)
    sim.connect("mode", "scope", dst_idx=3)
    sim.connect("sh", "scope", dst_idx=4)
    sim.connect("err", "scope", dst_idx=5)
    sim.connect("u_pid", "scope", dst_idx=6)
    sim.connect("energy", "scope", dst_idx=7)
    return sim, scope


# ---------------------------------------------------------------------------
# 参照実装 (flode を使わず同じ方程式を平文で解く)
# ---------------------------------------------------------------------------
def _r_raw(t: float) -> float:
    step = STEP_VALUE if t >= STEP_TIME else 0.0
    return float(step + R_SINE_AMP * np.sin(2 * np.pi * R_SINE_FREQ * t))


def _pulse(t: float) -> float:
    return 1.0 if (t % PULSE_PERIOD) < PULSE_PERIOD * 0.5 else 0.0


def _disturbance(t: float) -> float:
    sel = int(round(float(np.mod(math.floor(t * (1.0 / DIST_SLOT)), 3.0))))
    sel = min(max(sel, 0), 2)
    choices = (0.0, DIST_SINE_AMP * np.sin(2 * np.pi * DIST_SINE_FREQ * t), DIST_CONST)
    return float(choices[sel])


def _energy(theta: float, omega: float) -> float:
    return float((0.5 * J) * omega**2 + MGL * (1 - np.cos(theta)))


@dataclass
class _Disc:
    """離散状態 (flode の discrete_state 相当)。"""

    rsh: float = 0.0
    trig_prev: float = math.nan
    delay: npt.NDArray[np.float64] | None = None
    relay: float = 0.0
    dtf_u1: float = 0.0  # u[k-1]
    dtf_u2: float = 0.0  # u[k-2]
    dtf_y: float = 0.0  # y[k-1] → update で y[k]
    rl: float = 0.0

    def copy(self) -> _Disc:
        d = _Disc(**{k: v for k, v in self.__dict__.items() if k != "delay"})
        d.delay = None if self.delay is None else self.delay.copy()
        return d


def _signals(t: float, x: npt.NDArray[np.float64], d: _Disc) -> dict[str, float]:
    """時刻 t・連続状態 x・離散状態 d から代数信号を全て計算する。"""
    theta, omega, i_state = float(x[0]), float(x[1]), float(x[2])
    assert d.delay is not None
    y_del = float(d.delay[0])
    e = d.rsh - y_del
    abs_e = abs(e)
    kp = float(np.interp(abs_e, KP_BP, KP_TBL))
    u_pid = kp * e + KI * i_state + KD * d.dtf_y
    u_bb = BB_LEVEL * float(np.sign(e))
    u_sw = u_bb if d.relay >= 0.5 else u_pid
    u_sat = min(max(u_sw, -U_MAX), U_MAX)
    return {
        "theta": theta,
        "omega": omega,
        "y_del": y_del,
        "e": e,
        "abs_e": abs_e,
        "u_pid": u_pid,
        "u_sat": u_sat,
        "enabled": 1.0 if d.relay <= 0.0 else 0.0,
        "tau": d.rl,
        "energy": _energy(theta, omega),
    }


def reference_hybrid() -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """flode と同じ update-before-output 順序で閉ループを手計算する。"""
    n_steps = int(round(T_END / DT))
    r_ctrl = int(round(TS_CTRL / DT))
    r_sens = int(round(TS_SENSOR / DT))
    n_buf = max(1, math.ceil(DELAY / TS_SENSOR)) + 1

    d = _Disc(delay=np.zeros(n_buf))
    x = np.array([THETA0, 0.0, 0.0])
    times: list[float] = []
    rows: list[list[float]] = []

    def rhs(t: float, xx: npt.NDArray[np.float64], dd: _Disc) -> npt.NDArray[np.float64]:
        theta, omega = xx[0], xx[1]
        tau_total = dd.rl + _disturbance(t)
        alpha = (tau_total - C_DAMP * omega - MGL * np.sin(theta)) / J
        assert dd.delay is not None
        e = dd.rsh - float(dd.delay[0])
        di = e if dd.relay <= 0.0 else 0.0
        return np.array([omega, alpha, di])

    for k in range(n_steps + 1):
        t = k * DT
        # [A'] pre-fire の信号で離散 update
        pre = _signals(t, x, d)
        nd = d.copy()
        if k % r_sens == 0:
            assert d.delay is not None
            nd.delay = np.concatenate([d.delay[1:], [pre["theta"]]])
        if k % r_ctrl == 0:
            # Triggered S/H
            curr = _pulse(t)
            if d.trig_prev <= 0.0 < curr:
                nd.rsh = _r_raw(t)
            nd.trig_prev = curr
            # Relay
            if d.relay <= 0.5 and pre["abs_e"] >= RELAY_ON:
                nd.relay = 1.0
            elif d.relay > 0.5 and pre["abs_e"] <= RELAY_OFF:
                nd.relay = 0.0
            # 離散フィルタ: Ts y[k] = 0.5 Ts y[k-1] + u[k-1] - u[k-2]
            nd.dtf_y = 0.5 * d.dtf_y + (d.dtf_u1 - d.dtf_u2) / TS_CTRL
            nd.dtf_u2 = d.dtf_u1
            nd.dtf_u1 = pre["y_del"]
            # RateLimiter
            delta = pre["u_sat"] - d.rl
            delta = min(max(delta, -SLEW * TS_CTRL), SLEW * TS_CTRL)
            nd.rl = d.rl + delta
        d = nd
        # [A]/[E] post-fire の信号を記録
        post = _signals(t, x, d)
        times.append(t)
        rows.append(
            [
                post["theta"],
                post["omega"],
                post["tau"],
                d.relay,
                d.rsh,
                post["e"],
                post["u_pid"],
                post["energy"],
            ]
        )
        if k == n_steps:
            break
        # [B] 連続積分
        sol = solve_ivp(
            lambda tt, xx, dd=d: rhs(tt, xx, dd),
            (t, (k + 1) * DT),
            x,
            t_eval=[(k + 1) * DT],
            method="RK45",
            max_step=DT,
            rtol=RTOL,
            atol=ATOL,
        )
        x = sol.y[:, -1]
    return np.array(times), np.array(rows)


# ---------------------------------------------------------------------------
# 各チェック
# ---------------------------------------------------------------------------
def check_hybrid() -> tuple[CheckResult, Simulator, Scope, npt.NDArray[np.float64]]:
    t0 = time.perf_counter()
    sim, scope = build_hybrid_model()
    sim.run()
    t_flode = time.perf_counter() - t0
    t0 = time.perf_counter()
    t_ref, v_ref = reference_hybrid()
    t_refimpl = time.perf_counter() - t0

    t_sim = np.array(scope.times)
    v_sim = scope.values
    ok_shape = t_sim.shape == t_ref.shape and v_sim.shape == v_ref.shape
    if not ok_shape:
        return (
            CheckResult(
                "hybrid",
                False,
                f"shape mismatch: flode {v_sim.shape} vs ref {v_ref.shape}",
            ),
            sim,
            scope,
            v_ref,
        )
    err_t = float(np.max(np.abs(t_sim - t_ref)))
    per_sig = np.max(np.abs(v_sim - v_ref), axis=0)
    worst = float(per_sig.max())
    n_mode_switch = int(np.count_nonzero(np.diff(v_sim[:, 3])))
    n_sh_updates = int(np.count_nonzero(np.diff(v_sim[:, 4])))
    detail = (
        "max|dA| per signal = "
        + ", ".join(f"{lab}:{e:.1e}" for lab, e in zip(scope.labels, per_sig, strict=True))
        + f"; max|dt|={err_t:.1e}; mode switches={n_mode_switch}, S/H updates={n_sh_updates}; "
        f"flode {t_flode:.1f}s / ref {t_refimpl:.1f}s"
    )
    return CheckResult("hybrid", worst < 1e-9 and err_t == 0.0, detail), sim, scope, v_ref


def _save_load_run(sim: Simulator) -> tuple[bool, str, npt.NDArray[np.float64] | None]:
    """save → load → run。失敗時は (False, 例外要約, None)。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "torture.flw.json"
        sim.save(path)
        try:
            sim2 = Simulator.load(path)
        except Exception as exc:  # noqa: BLE001 - 報告用に要約
            return False, f"{type(exc).__name__}: {str(exc)[:90]}", None
    sim2.run()
    scope2 = sim2.get_block("scope")
    assert isinstance(scope2, Scope)
    return True, "ok", scope2.values


def check_roundtrip(sim_nested: Simulator, scope_nested: Scope) -> CheckResult:
    """構造不変性 (入れ子 vs 平坦) と JSON round-trip を確認する。"""
    parts = []
    passed = True
    v0 = scope_nested.values

    # (1) 入れ子 (2 階層) モデルの save → load → run
    ok, msg, v1 = _save_load_run(sim_nested)
    if ok and v1 is not None:
        ok = bool(np.array_equal(v0, v1))
        msg = f"bit-identical={ok}"
    passed &= ok
    parts.append(f"nested round-trip: {msg}")

    # (2) 同じ演算を平坦に組んだモデルとの bit 一致 (入れ子 Subsystem の透過性)
    sim_flat, scope_flat = build_hybrid_model(nested=False)
    sim_flat.run()
    same_flat = bool(np.array_equal(v0, scope_flat.values))
    worst = 0.0 if same_flat else float(np.max(np.abs(v0 - scope_flat.values)))
    passed &= same_flat
    parts.append(f"nested vs flat: bit-identical={same_flat} (max|dA|={worst:.1e})")

    # (3) 平坦モデルの save → load → run
    ok, msg, v2 = _save_load_run(sim_flat)
    if ok and v2 is not None:
        ok = bool(np.array_equal(v0, v2))
        msg = f"bit-identical={ok}"
    passed &= ok
    parts.append(f"flat round-trip: {msg}")
    return CheckResult("roundtrip", passed, "; ".join(parts))


def check_linearize() -> CheckResult:
    details = []
    passed = True
    for theta_star in (0.0, math.pi):
        sim = Simulator(t_end=1.0, dt=DT)
        sim.add(build_pendulum_subsystem(C_DAMP, theta_star))
        ls = sim.linearize()
        # Subsystem 内部状態は "plant.x[i]" と平坦化されるので、出力行列 C
        # (出力 0 = θ、出力 1 = ω) からどの状態がどちらかを特定する
        i_th = int(np.argmax(np.abs(ls.C[0])))
        i_om = int(np.argmax(np.abs(ls.C[1])))
        a_num = np.array(
            [
                [ls.A[i_th, i_th], ls.A[i_th, i_om]],
                [ls.A[i_om, i_th], ls.A[i_om, i_om]],
            ]
        )
        a_exact = np.array([[0.0, 1.0], [-MGL * math.cos(theta_star) / J, -C_DAMP / J]])
        b_num = np.array([ls.B[i_th, 0], ls.B[i_om, 0]])
        b_exact = np.array([0.0, 1.0 / J])
        err = max(float(np.max(np.abs(a_num - a_exact))), float(np.max(np.abs(b_num - b_exact))))
        stable = bool(np.all(np.linalg.eigvals(a_num).real < 0))
        expect_stable = theta_star == 0.0
        ok = err < 1e-6 and stable == expect_stable
        passed &= ok
        details.append(
            f"theta*={theta_star:.3f}: max|dA,dB|={err:.1e}, "
            f"eig={np.round(np.linalg.eigvals(a_num), 4)}, stable={stable}"
        )
    return CheckResult("linearize", passed, "; ".join(details))


def check_pendulum_conservation() -> CheckResult:
    theta0 = 2.0
    t_end = 12.0
    sim = Simulator(t_end=t_end, dt=0.002, rtol=1e-10, atol=1e-13)
    plant = sim.add(build_pendulum_subsystem(0.0, theta0))
    sim.add(Constant(value=0.0, id="zero"))
    scope = sim.add(Scope(n_inputs=2, labels=["theta", "omega"], buffer_mode="unbounded", id="sc"))
    sim.connect("zero", plant)
    sim.connect(plant, scope, src_idx=0, dst_idx=0)
    sim.connect(plant, scope, src_idx=1, dst_idx=1)
    sim.run()
    assert isinstance(scope, Scope)
    t = np.array(scope.times)
    th, om = scope.values[:, 0], scope.values[:, 1]
    energy = 0.5 * J * om**2 + MGL * (1 - np.cos(th))
    e0 = MGL * (1 - math.cos(theta0))
    drift = float(np.max(np.abs(energy - e0)) / e0)

    # 厳密周期: T = 4 sqrt(L/g) K(m), m = sin²(θ0/2)
    period_exact = 4.0 * math.sqrt(L / G) * float(ellipk(math.sin(theta0 / 2) ** 2))
    # ω のゼロクロス (θ の折返し) を線形補間で拾い、半周期の間隔から周期を推定
    idx = np.where(np.sign(om[:-1]) != np.sign(om[1:]))[0]
    idx = idx[om[idx] != 0.0]
    crossings = t[idx] - om[idx] * (t[idx + 1] - t[idx]) / (om[idx + 1] - om[idx])
    half_periods = np.diff(crossings)
    period_num = float(2.0 * np.mean(half_periods))
    rel_err = abs(period_num - period_exact) / period_exact
    small_angle = 2 * math.pi * math.sqrt(L / G)
    ok = drift < 1e-7 and rel_err < 1e-6 and len(half_periods) >= 4
    return CheckResult(
        "pendulum",
        ok,
        f"energy drift={drift:.1e}, period num={period_num:.7f} exact={period_exact:.7f} "
        f"(rel err {rel_err:.1e}; small-angle would be {small_angle:.5f}), "
        f"{len(half_periods)} half-periods",
    )


def check_dde() -> CheckResult:
    dt = 0.002
    tau = 1.0
    t_end = 6.0
    n_lag = int(round(tau / dt))
    sim = Simulator(t_end=t_end, dt=dt, rtol=1e-10, atol=1e-13)
    sim.add(Integrator(x0=1.0, id="x"))
    sim.add(TransportDelay(delay_time=tau, sample_time=dt, initial_output=1.0, id="lag"))
    sim.add(Gain(k=-1.0, id="neg"))
    # Mux/Demux を経由させて SM-B 経路でもスカラー値が保存されることを確認
    sim.add(Mux(n=2, id="mux"))
    sim.add(Demux(n=2, id="demux"))
    scope = sim.add(Scope(n_inputs=2, labels=["x", "x_lag"], buffer_mode="unbounded", id="sc"))
    sim.connect("x", "lag")
    sim.connect("lag", "neg")
    sim.connect("neg", "x")
    sim.connect("x", "mux", dst_idx=0)
    sim.connect("lag", "mux", dst_idx=1)
    sim.connect("mux", "demux")
    sim.connect("demux", "sc", src_idx=0, dst_idx=0)
    sim.connect("demux", "sc", src_idx=1, dst_idx=1)
    sim.run()
    assert isinstance(scope, Scope)
    t = np.array(scope.times)
    x_sim = scope.values[:, 0]

    # (a) flode が実際に解いている漸化式 x_{k+1} = x_k - dt * x_{k-n_lag}
    n = len(t)
    x_rec = np.ones(n + n_lag)  # 先頭 n_lag 個は履歴 (=1)
    for k in range(n - 1):
        x_rec[n_lag + k + 1] = x_rec[n_lag + k] - dt * x_rec[k]
    err_rec = float(np.max(np.abs(x_sim - x_rec[n_lag:])))

    # (b) 段階法による厳密解 x(t) = Σ_{j=0}^{⌊t⌋+1} (-1)^j (t+1-j)^j / j!
    #     (x ≡ 1 on [-1, 0]; 例: t∈[0,1] で 1-t、x(2) = -1/2)
    def exact(tt: float) -> float:
        return float(
            sum((-1) ** j * (tt + 1 - j) ** j / math.factorial(j) for j in range(int(tt) + 2))
        )

    x_exact = np.array([exact(tt) for tt in t])
    err_exact = float(np.max(np.abs(x_sim - x_exact)))
    ok = err_rec < 1e-12 and err_exact < 5 * dt
    return CheckResult(
        "dde",
        ok,
        f"vs recursion max|dA|={err_rec:.1e} (machine precision expected); "
        f"vs exact solution max|dA|={err_exact:.2e} (O(dt)={dt} expected); "
        f"x(6)={x_sim[-1]:.6f} exact={x_exact[-1]:.6f}",
    )


# ---------------------------------------------------------------------------
# 可視化
# ---------------------------------------------------------------------------
def plot_hybrid(scope: Scope, v_ref: npt.NDArray[np.float64], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.array(scope.times)
    v = scope.values
    lab = scope.labels
    fig, axes = plt.subplots(4, 1, figsize=(10, 11), sharex=True)
    ax = axes[0]
    ax.plot(t, v[:, 4], "k--", lw=1, label="r_sh (S/H setpoint)")
    ax.plot(t, v[:, 0], label="theta")
    ax.plot(t, v[:, 5], alpha=0.6, label="e")
    ax.set_ylabel("rad")
    ax.legend(loc="upper right", ncol=3)
    ax = axes[1]
    ax.plot(t, v[:, 2], label="tau (after sat + rate limit)")
    ax.plot(t, v[:, 6], alpha=0.5, label="u_pid (raw)")
    ax.step(t, v[:, 3] * U_MAX, where="post", color="r", lw=0.8, label="mode x 4 (1=bang-bang)")
    ax.set_ylim(-U_MAX * 1.3, U_MAX * 1.3)
    ax.set_ylabel("N m")
    ax.legend(loc="upper right", ncol=3)
    ax = axes[2]
    ax.plot(t, v[:, 1], label="omega")
    ax.plot(t, v[:, 7], label="energy")
    ax.legend(loc="upper right", ncol=2)
    ax = axes[3]
    for i in range(v.shape[1]):
        diff = np.abs(v[:, i] - v_ref[:, i])
        ax.semilogy(t, np.maximum(diff, 1e-18), lw=0.7, label=lab[i])
    ax.set_ylabel("|flode - reference|")
    ax.set_xlabel("t [s]")
    ax.legend(loc="upper right", ncol=4, fontsize=8)
    for a in axes:
        a.grid(True, alpha=0.3)
    fig.suptitle("Hybrid torture model: flode vs hand-written reference")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------
def main() -> int:
    results: list[CheckResult] = []
    res, sim, scope, v_ref = check_hybrid()
    results.append(res)
    # 1 つのチェックの例外で他のチェック結果が隠れないよう個別に捕捉する
    for name, fn in (
        ("roundtrip", lambda: check_roundtrip(sim, scope)),
        ("linearize", check_linearize),
        ("pendulum", check_pendulum_conservation),
        ("dde", check_dde),
    ):
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 - 検証レポート用に全例外を集約
            results.append(CheckResult(name, False, f"EXCEPTION {type(exc).__name__}: {exc}"))

    out_png = Path(__file__).resolve().parents[2] / "hybrid_torture_verification.png"
    if v_ref.shape == scope.values.shape:
        plot_hybrid(scope, v_ref, out_png)

    all_ok = True
    for r in results:
        all_ok &= r.passed
        _logger.info("[%s] %-10s %s", "PASS" if r.passed else "FAIL", r.name, r.detail)
    _logger.info("plot: %s", out_png)
    _logger.info("OVERALL: %s", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
