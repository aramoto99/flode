"""入れ子 (2 階層以上) Subsystem の save / load round-trip 回帰テスト。

2026-09-13 の複雑モデル検証で発見: ``Subsystem._from_dict`` が内側 Subsystem の
dict をそのまま ``Subsystem(blocks=[dict, ...])`` に渡すため、2 階層入れ子の
モデルを ``Simulator.load`` すると ``ModelLoadError`` (Expected Block instance,
got dict) になっていた。ADR-0009 §(6) は再帰 dict 化を前提にしている。
"""

from __future__ import annotations

import json

import numpy as np

from flode import Inport, Outport, Simulator, Subsystem
from flode.blocks import Constant, Gain, Integrator, Scope


def _inner(k: float) -> Subsystem:
    inner = Subsystem(id="inner")
    inner.add(Inport(port_idx=0, id="i"))
    inner.add(Gain(k=k, id="g"))
    inner.add(Outport(port_idx=0, id="o"))
    inner.connect("i", "g")
    inner.connect("g", "o")
    return inner


def _outer_with_nested(k: float, depth: int) -> Subsystem:
    """depth 段の入れ子を作る (depth=1 で inner を直接内包)。"""
    child = _inner(k)
    for level in range(depth - 1):
        wrap = Subsystem(id=f"mid{level}")
        wrap.add(Inport(port_idx=0, id="i"))
        wrap.add(child)
        wrap.add(Outport(port_idx=0, id="o"))
        wrap.connect("i", child.id)
        wrap.connect(child.id, "o")
        child = wrap
    outer = Subsystem(id="outer")
    outer.add(Inport(port_idx=0, id="i"))
    outer.add(child)
    outer.add(Integrator(x0=0.0, id="acc"))
    outer.add(Outport(port_idx=0, id="o"))
    outer.connect("i", child.id)
    outer.connect(child.id, "acc")
    outer.connect("acc", "o")
    return outer


def _mask_outer_with_nested_dict(kp: float) -> dict:
    """mask 付き外側 Subsystem の中に placeholder ``$Kp`` を使う入れ子 Subsystem を置く JSON dict。"""
    return {
        "id": "outer",
        "type": "flode.subsystems.subsystem.Subsystem",
        "params": {
            "mask_params": [{"name": "Kp", "type": "float", "default": 1.0}],
            "mask_values": {"Kp": kp},
            "blocks": [
                {"id": "i", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
                {
                    "id": "inner",
                    "type": "flode.subsystems.subsystem.Subsystem",
                    "params": {
                        "blocks": [
                            {
                                "id": "i",
                                "type": "flode.subsystems.ports.Inport",
                                "params": {"port_idx": 0},
                            },
                            {
                                "id": "g",
                                "type": "flode.blocks.mathops.Gain",
                                "params": {"k": "$Kp"},
                            },
                            {
                                "id": "o",
                                "type": "flode.subsystems.ports.Outport",
                                "params": {"port_idx": 0},
                            },
                        ],
                        "connections": [
                            {"src": "i", "src_idx": 0, "dst": "g", "dst_idx": 0},
                            {"src": "g", "src_idx": 0, "dst": "o", "dst_idx": 0},
                        ],
                    },
                },
                {"id": "o", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
            ],
            "connections": [
                {"src": "i", "src_idx": 0, "dst": "inner", "dst_idx": 0},
                {"src": "inner", "src_idx": 0, "dst": "o", "dst_idx": 0},
            ],
        },
    }


def _model_dict(sub_spec: dict) -> dict:
    return {
        "schema_version": "0.6",
        "simulator": {
            "t_end": 0.05,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [
            {"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
            sub_spec,
            {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
        ],
        "connections": [
            {"src": "c", "src_idx": 0, "dst": "outer", "dst_idx": 0},
            {"src": "outer", "src_idx": 0, "dst": "sc", "dst_idx": 0},
        ],
    }


class TestMaskedOuterWithNestedSubsystem:
    """code-reviewer MUST (2026-09-13): mask 付き親 + 入れ子 Subsystem の load → run → 値変更。"""

    def test_load_run_and_set_mask_value(self, tmp_path) -> None:
        path = tmp_path / "mask_nested.flw.json"
        path.write_text(json.dumps(_model_dict(_mask_outer_with_nested_dict(kp=3.0))), "utf-8")
        sim = Simulator.load(path)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 3.0)

        outer = sim.get_block("outer")
        assert isinstance(outer, Subsystem)
        # 入れ子 Subsystem の再構築経路 (_resolve_mask_placeholders) が factory を使うこと
        outer.set_mask_value("Kp", 5.0)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 5.0)

    def test_save_load_round_trip_keeps_values(self, tmp_path) -> None:
        path = tmp_path / "mask_nested.flw.json"
        path.write_text(json.dumps(_model_dict(_mask_outer_with_nested_dict(kp=2.5))), "utf-8")
        sim = Simulator.load(path)
        out = tmp_path / "rt.flw.json"
        sim.save(out)
        sim2 = Simulator.load(out)
        sim.run()
        sim2.run()
        np.testing.assert_array_equal(sim.get_block("sc").values, sim2.get_block("sc").values)
        np.testing.assert_allclose(sim2.get_block("sc").values[:, 0], 2.5)


class TestNestedSubsystemRoundTrip:
    def test_two_level_nested_subsystem_round_trip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.5, dt=0.01, rtol=1e-10, atol=1e-13)
        sim.add(Constant(value=2.0, id="src"))
        sim.add(_outer_with_nested(k=1.5, depth=1))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "outer")
        sim.connect("outer", "scope")

        path = tmp_path / "nested.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        v1 = sim.get_block("scope").values
        v2 = sim2.get_block("scope").values
        np.testing.assert_array_equal(v1, v2)
        # 2.0 * 1.5 を 0.5 s 積分 = 1.5
        np.testing.assert_allclose(v1[-1, 0], 1.5, atol=1e-9)

    def test_three_level_nested_subsystem_round_trip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.2, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(_outer_with_nested(k=3.0, depth=2))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "outer")
        sim.connect("outer", "scope")

        path = tmp_path / "nested3.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_array_equal(sim.get_block("scope").values, sim2.get_block("scope").values)
