"""ADR-0039: Subsystem `n_inputs` / `n_outputs` / `port_shapes_in` / `port_shapes_out` 派生 property のテスト。

v0.14.0 で SSOT 是正された Subsystem の派生 property semantics を直接検証する。
"""

from __future__ import annotations

import pytest

from flode.exceptions import BlockSpecError
from flode.subsystems import Inport, Outport, Subsystem


class TestSubsystemDerivedNInputs:
    def test_empty_subsystem_has_zero_n_inputs(self) -> None:
        sub = Subsystem()
        assert sub.n_inputs == 0
        assert sub.n_outputs == 0

    def test_adding_inport_increments_n_inputs(self) -> None:
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        assert sub.n_inputs == 1
        sub.add(Inport(port_idx=1))
        assert sub.n_inputs == 2

    def test_adding_outport_increments_n_outputs(self) -> None:
        sub = Subsystem()
        sub.add(Outport(port_idx=0))
        assert sub.n_outputs == 1

    def test_input_sources_grows_with_inport(self) -> None:
        # ADR-0039: input_sources は Inport 追加で動的に拡張
        sub = Subsystem()
        assert len(sub.input_sources) == 0
        sub.add(Inport(port_idx=0))
        assert len(sub.input_sources) == 1
        sub.add(Inport(port_idx=1))
        assert len(sub.input_sources) == 2

    def test_outport_does_not_extend_input_sources(self) -> None:
        sub = Subsystem()
        sub.add(Outport(port_idx=0))
        assert len(sub.input_sources) == 0  # Outport は subsystem 出力側

    def test_port_shapes_in_derived_from_inner_inports(self) -> None:
        sub = Subsystem()
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        sub.add(Inport(port_idx=1, port_shape=(2, 4)))
        assert sub.port_shapes_in == ((3,), (2, 4))

    def test_port_shapes_out_derived_from_inner_outports(self) -> None:
        sub = Subsystem()
        sub.add(Outport(port_idx=0, port_shape=()))
        sub.add(Outport(port_idx=1, port_shape=(5,)))
        assert sub.port_shapes_out == ((), (5,))

    def test_legacy_n_inputs_argument_rejected(self) -> None:
        with pytest.raises(TypeError, match="were removed in v2.0"):
            Subsystem(n_inputs=2, n_outputs=1)  # type: ignore[call-arg]

    def test_legacy_port_shapes_argument_rejected(self) -> None:
        with pytest.raises(TypeError, match="were removed in v2.0"):
            Subsystem(port_shapes_in=((3,),))  # type: ignore[call-arg]


# ADR-0058 v0.38.0: TriggeredSubsystem class は削除済。等価動作は Subsystem +
# 内部 Trigger control block で実現される (tests/subsystems/test_subsystem_trigger_integration.py 参照)。


class TestPortIdxValidation:
    """ADR-0039 §Decision §(2): 派生 count は自動成立だが port_idx 連番強制は維持。"""

    def test_port_idx_gap_raises_on_build(self) -> None:
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        sub.add(Inport(port_idx=2))  # 飛び番号 (1 を抜かす)
        sub.add(Outport(port_idx=0))
        with pytest.raises(BlockSpecError, match="do not cover"):
            sub._build()

    def test_port_idx_duplicate_raises_on_build(self) -> None:
        sub = Subsystem()
        sub.add(Inport(port_idx=0, id="in0_a"))
        sub.add(Inport(port_idx=0, id="in0_b"))  # 重複
        sub.add(Outport(port_idx=0))
        with pytest.raises(BlockSpecError, match="do not cover"):
            sub._build()

    def test_sequential_port_idx_passes_build(self) -> None:
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        sub.add(Inport(port_idx=1))
        sub.add(Inport(port_idx=2))
        sub.add(Outport(port_idx=0))
        sub._build()  # 例外なし
        assert sub.n_inputs == 3
        assert sub.n_outputs == 1
