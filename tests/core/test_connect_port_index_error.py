"""``connect`` の範囲外ポートが flode のドメイン例外 (``PortIndexError``) になることの回帰テスト。

2026-09-14 発見: ``Simulator.connect`` / ``Subsystem.connect`` が builtin ``IndexError`` を
そのまま投げていた (プロジェクト規約: 素の builtin 例外を raise しない)。後方互換のため
``PortIndexError`` は ``BlockSpecError`` と ``IndexError`` の両方を継承する
(``UnknownBlockIdError(FlodeError, KeyError)`` と同じ流儀)。
"""

from __future__ import annotations

import pytest

from flode import Inport, Outport, PortIndexError, Simulator, Subsystem
from flode.blocks import Constant, Gain, Scope, Sum
from flode.exceptions import BlockSpecError, FlodeError, ModelLoadError


def test_port_index_error_hierarchy() -> None:
    assert issubclass(PortIndexError, BlockSpecError)
    assert issubclass(PortIndexError, FlodeError)
    assert issubclass(PortIndexError, IndexError)


@pytest.mark.parametrize(
    ("src_idx", "dst_idx"),
    [(0, 7), (0, -1), (3, 0), (-1, 0)],
)
def test_simulator_connect_out_of_range_raises_domain_error(src_idx: int, dst_idx: int) -> None:
    sim = Simulator(t_end=0.1, dt=0.01)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(Sum(signs="++", id="s"))
    with pytest.raises(PortIndexError, match="out of range"):
        sim.connect("c", "s", src_idx=src_idx, dst_idx=dst_idx)


def test_connect_from_scope_output_raises_domain_error() -> None:
    sim = Simulator(t_end=0.1, dt=0.01)
    sim.add(Scope(id="sc"))
    sim.add(Gain(id="g"))
    with pytest.raises(PortIndexError, match="n_outputs=0"):
        sim.connect("sc", "g")


def test_subsystem_connect_out_of_range_raises_domain_error() -> None:
    sub = Subsystem(id="sub")
    sub.add(Inport(port_idx=0, id="i"))
    sub.add(Gain(id="g"))
    sub.add(Outport(port_idx=0, id="o"))
    with pytest.raises(PortIndexError, match="out of range"):
        sub.connect("i", "g", dst_idx=2)


def test_from_dict_still_wraps_into_model_load_error() -> None:
    data = {
        "schema_version": "0.15",
        "simulator": {
            "t_end": 0.1,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [
            {"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
            {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 2.0}},
        ],
        "connections": [{"src": "c", "src_idx": 0, "dst": "g", "dst_idx": 5}],
    }
    with pytest.raises(ModelLoadError, match="Invalid connection"):
        Simulator.from_dict(data)


def test_port_index_error_carries_block_id_for_log_tab_jump() -> None:
    """code-reviewer SHOULD: ADR-0056 の「ログタブからブロックへジャンプ」用に block_id を持つ。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(Sum(signs="++", id="s"))
    with pytest.raises(PortIndexError) as info:
        sim.connect("c", "s", dst_idx=9)
    assert info.value.block_id == "s"
    with pytest.raises(PortIndexError) as info2:
        sim.connect("c", "s", src_idx=4, dst_idx=0)
    assert info2.value.block_id == "c"
