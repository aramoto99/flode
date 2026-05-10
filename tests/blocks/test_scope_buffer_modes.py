"""``Scope.buffer_mode`` ring / bounded / unbounded のテスト (ADR-0042 §論点 2)。

容量到達時の挙動 (ring=FIFO drop / bounded=warn 後黙る / unbounded=無制限) と、
``Simulator.t_end=inf`` × ``buffer_mode=unbounded`` combo の reject を検証する。
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Scope
from pyflw.exceptions import BlockSpecError, BufferOverflowWarning


class TestBufferModeAcceptance:
    """``buffer_mode`` の入力検証。"""

    def test_default_is_ring(self) -> None:
        scope = Scope(n_inputs=1)
        assert scope.buffer_mode == "ring"
        assert scope.buffer_capacity == 100_000

    def test_explicit_ring(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=10)
        assert scope.buffer_mode == "ring"
        assert scope.buffer_capacity == 10

    def test_explicit_bounded(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="bounded", buffer_capacity=5)
        assert scope.buffer_mode == "bounded"

    def test_explicit_unbounded(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="unbounded")
        assert scope.buffer_mode == "unbounded"

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="buffer_mode"):
            Scope(n_inputs=1, buffer_mode="invalid")  # type: ignore[arg-type]

    def test_invalid_capacity_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="buffer_capacity"):
            Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=0)


class TestRingMode:
    """``ring`` mode は容量到達後 FIFO で最古を drop。"""

    def test_below_capacity_keeps_all(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=5)
        for i in range(3):
            scope.record(float(i), np.array([float(i)]))
        assert list(scope.times) == [0.0, 1.0, 2.0]
        assert scope.values.tolist() == [[0.0], [1.0], [2.0]]

    def test_at_capacity_keeps_all(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=5)
        for i in range(5):
            scope.record(float(i), np.array([float(i)]))
        assert len(scope.times) == 5
        assert list(scope.times) == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_above_capacity_drops_oldest(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=3)
        for i in range(10):
            scope.record(float(i), np.array([float(i)]))
        # 最古 0..6 が drop され、直近 7,8,9 だけ残る
        assert len(scope.times) == 3
        assert list(scope.times) == [7.0, 8.0, 9.0]
        assert scope.values.tolist() == [[7.0], [8.0], [9.0]]

    def test_reset_clears(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="ring", buffer_capacity=5)
        for i in range(3):
            scope.record(float(i), np.array([float(i)]))
        scope.reset()
        assert len(scope.times) == 0


class TestBoundedMode:
    """``bounded`` mode は容量到達後 warn して黙って捨てる (= 1 回だけ警告)。"""

    def test_below_capacity_keeps_all(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="bounded", buffer_capacity=5)
        for i in range(3):
            scope.record(float(i), np.array([float(i)]))
        assert scope.times == [0.0, 1.0, 2.0]

    def test_at_capacity_warns_and_stops(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="bounded", buffer_capacity=3)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for i in range(5):
                scope.record(float(i), np.array([float(i)]))
            # 0..2 で記録、3 で warning + drop、4 で 黙って drop
            buffer_warnings = [x for x in w if issubclass(x.category, BufferOverflowWarning)]
            assert len(buffer_warnings) == 1, (
                f"BufferOverflowWarning should fire exactly once, got {len(buffer_warnings)}"
            )
        # 直近 3 件 (= 0..2) のみ保持
        assert scope.times == [0.0, 1.0, 2.0]

    def test_warning_message_contains_id(self) -> None:
        scope = Scope(n_inputs=1, id="my_scope", buffer_mode="bounded", buffer_capacity=2)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for i in range(3):
                scope.record(float(i), np.array([float(i)]))
            buffer_warnings = [x for x in w if issubclass(x.category, BufferOverflowWarning)]
            assert "my_scope" in str(buffer_warnings[0].message)

    def test_reset_re_enables_warning(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="bounded", buffer_capacity=2)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            for i in range(5):
                scope.record(float(i), np.array([float(i)]))
        scope.reset()
        # reset 後はもう一度 fire するか
        with warnings.catch_warnings(record=True) as w2:
            warnings.simplefilter("always")
            for i in range(5):
                scope.record(float(i), np.array([float(i)]))
            buffer_warnings = [x for x in w2 if issubclass(x.category, BufferOverflowWarning)]
            assert len(buffer_warnings) == 1


class TestUnboundedMode:
    """``unbounded`` mode は capacity 制約なし、無制限に append。"""

    def test_grows_indefinitely(self) -> None:
        scope = Scope(n_inputs=1, buffer_mode="unbounded")
        for i in range(1000):
            scope.record(float(i), np.array([float(i)]))
        assert len(scope.times) == 1000
        assert scope.times[-1] == 999.0


class TestUnboundedRejectedWithInfTEnd:
    """``Simulator.t_end=inf`` × ``buffer_mode=unbounded`` combo は build 時 reject。"""

    def test_inf_plus_unbounded_rejects(self) -> None:
        sim = Simulator(t_end="inf")
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope", buffer_mode="unbounded"))
        sim.connect("src", "scope")
        with pytest.raises(BlockSpecError, match="unbounded.*not allowed.*t_end=inf"):
            sim.run()

    def test_finite_plus_unbounded_ok(self) -> None:
        # 有限 t_end なら unbounded でも問題なし (= 既存挙動相当)
        sim = Simulator(t_end=0.01, dt=0.005)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope", buffer_mode="unbounded"))
        sim.connect("src", "scope")
        sim.run()  # raises 無し
        scope = sim.get_block("scope")
        assert len(scope.times) >= 1

    def test_inf_plus_ring_default_ok(self) -> None:
        # inf でも default (ring) は build 通る
        sim = Simulator(t_end="inf")
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope"))  # default = ring
        sim.connect("src", "scope")

        def stopper(t: float, t_end: float) -> bool:
            # 数 step 走ってすぐ停止
            return t < 0.05

        sim.on_step_callback = stopper
        sim.run()  # raises 無し
        assert math.isinf(sim.t_end)

    def test_inf_plus_bounded_ok(self) -> None:
        sim = Simulator(t_end="inf")
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope", buffer_mode="bounded", buffer_capacity=10))
        sim.connect("src", "scope")

        def stopper(t: float, t_end: float) -> bool:
            return t < 0.05

        sim.on_step_callback = stopper
        sim.run()
        # 最初の 5 step (= 0.05 まで) が記録される
        scope = sim.get_block("scope")
        assert len(scope.times) >= 1


class TestRingPersistsThroughSimulation:
    """``ring`` mode で Simulator.run 中の wrap 動作。"""

    def test_ring_keeps_only_recent_during_long_finite_run(self) -> None:
        # capacity 10、step 100 回 → 直近 10 step のみ残る
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(id="scope", buffer_mode="ring", buffer_capacity=10))
        sim.connect("src", "scope")
        sim.run()
        scope = sim.get_block("scope")
        assert len(scope.times) == 10
        # 最後の time は ~1.0
        assert scope.times[-1] == pytest.approx(1.0)
