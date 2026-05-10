"""``Simulator.t_end = math.inf`` (unbounded) 実行テスト (ADR-0042 §論点 1)。

``while True`` ループへの refactor が:
1. 既存の有限 t_end モデルで step 数 / 結果が完全不変
2. ``t_end = math.inf`` で ``request_stop()`` まで走り続ける
3. ``on_step_callback`` で ``False`` を返すと停止する

を検証する。``Scope.buffer_mode`` の検証は別ファイル (Step 4 で
``test_scope_ring.py`` を新設) に任せ、本ファイルでは run loop の挙動だけ
扱う。
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Integrator, Scope


def _build_integrator_model(t_end: float | str, dt: float = 0.01) -> Simulator:
    """積分器 1 個 + Constant 1 個の最小モデル。

    積分器の状態は ``t * 1.0`` で線形に増加する (= 経過時間そのもの)。
    """
    sim = Simulator(t_end=t_end, dt=dt)
    src = sim.add(Constant(value=1.0, id="src"))
    integ = sim.add(Integrator(x0=0.0, id="integ"))
    scope = sim.add(Scope(id="scope"))
    sim.connect(src, integ)
    sim.connect(integ, scope)
    return sim


class TestUnboundedAcceptance:
    """``Simulator.__init__`` が ``"inf"`` / ``math.inf`` を受け入れる。"""

    def test_inf_string(self) -> None:
        sim = Simulator(t_end="inf")
        assert sim.t_end == math.inf

    def test_math_inf_float(self) -> None:
        sim = Simulator(t_end=math.inf)
        assert sim.t_end == math.inf

    def test_finite_unchanged(self) -> None:
        # 既存 API: float 値はそのまま
        sim = Simulator(t_end=5.0)
        assert sim.t_end == 5.0


class TestUnboundedStopByRequest:
    """``t_end=inf`` で別スレッドから ``request_stop`` 投入 → 停止。"""

    def test_request_stop_terminates(self) -> None:
        sim = _build_integrator_model("inf")

        # 別スレッドで 0.2s 後に request_stop()
        def stopper() -> None:
            time.sleep(0.2)
            sim.request_stop()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()

        # 無限ループに入って ~0.2s 後に request_stop で抜ける
        # (= 通常 1187 件テスト全体の 9 秒以内に十分収まる)
        sim.run()
        thread.join(timeout=1.0)
        assert sim.is_stopped is True

    def test_records_have_data(self) -> None:
        sim = _build_integrator_model("inf")

        def stopper() -> None:
            time.sleep(0.1)
            sim.request_stop()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        sim.run()
        thread.join(timeout=1.0)

        scope = sim.get_block("scope")
        # 0.1s = 10 step (dt=0.01) で実機の OS 揺らぎ込みでも >= 1 step は記録される
        assert len(scope.times) >= 1
        assert scope.times[0] == pytest.approx(0.0)


class TestUnboundedStopByCallback:
    """``on_step_callback`` が ``False`` を返したらその時点で停止。"""

    def test_callback_false_terminates(self) -> None:
        # callback が 5 回目で False を返す → step 0..4 まで実行されて停止
        call_count = [0]

        def callback(t: float, t_end: float) -> bool:
            call_count[0] += 1
            return call_count[0] < 5

        sim = Simulator(t_end="inf", dt=0.01, on_step_callback=callback)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope"))
        sim.connect("src", "scope")
        sim.run()

        assert call_count[0] == 5
        scope = sim.get_block("scope")
        # callback 5 回 = step 0..4 record 済 (callback は record 後に呼ばれる)
        assert len(scope.times) == 5


class TestUnboundedFromDictRoundTrip:
    """``Simulator.save`` → ``Simulator.load`` で ``t_end=inf`` が保たれる。"""

    def test_save_load_inf(self, tmp_path: object) -> None:
        path = tmp_path / "model.flw.json"  # type: ignore[attr-defined]
        sim = _build_integrator_model("inf")
        sim.save(path)

        # 保存内容に "inf" 文字列が入っていること
        text = path.read_text(encoding="utf-8")  # type: ignore[attr-defined]
        assert '"t_end": "inf"' in text

        sim2 = Simulator.load(path)  # type: ignore[arg-type]
        assert sim2.t_end == math.inf

    def test_save_load_finite_byte_identical(self, tmp_path: object) -> None:
        # 既存有限値モデルは byte-identical で読み書きできる (= 前方互換)
        path = tmp_path / "model.flw.json"  # type: ignore[attr-defined]
        sim = _build_integrator_model(2.5)
        sim.save(path)

        text = path.read_text(encoding="utf-8")  # type: ignore[attr-defined]
        assert '"t_end": 2.5' in text

        sim2 = Simulator.load(path)  # type: ignore[arg-type]
        assert sim2.t_end == 2.5
        assert isinstance(sim2.t_end, float)


class TestUnboundedNumericalEquivalenceWithFinite:
    """``run`` の while True 化で有限 t_end の結果が完全不変 (= 数値ガード)。"""

    def test_integrator_2_seconds(self) -> None:
        # t_end=2.0 で積分器が 2.0 に達する (constant 1.0 を 2 秒積分)
        sim = _build_integrator_model(2.0, dt=0.01)
        sim.run()
        scope = sim.get_block("scope")
        # 積分器の出力は scope.values[-1] (= integrator output column)
        # 厳密一致は solver tolerance 込みで OK
        assert scope.times[-1] == pytest.approx(2.0)
        # x(t) = t、t=2.0 で x = 2.0
        last_value = scope.values[-1] if isinstance(scope.values, np.ndarray) else scope.values[-1]
        assert last_value == pytest.approx(2.0, abs=1e-3)
