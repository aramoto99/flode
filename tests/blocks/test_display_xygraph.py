"""Display / XYGraph (Phase 3 後 sink 拡張) のテスト。

Simulink Display / XY Graph 相当。Scope と同じ duck-type interface
(``record`` / ``times`` / ``values`` / ``labels``) を持つ。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Display, Gain, Sine, XYGraph
from pyflw.exceptions import BlockSpecError

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


class TestDisplay:
    def test_default_shape(self) -> None:
        d = Display()
        assert d.n_inputs == 1
        assert d.n_outputs == 0
        assert d.decimals == 3
        assert d.labels == ["in0"]

    def test_n_inputs_must_be_positive(self) -> None:
        with pytest.raises(BlockSpecError, match="n_inputs must be >= 1"):
            Display(n_inputs=0)

    def test_decimals_must_be_non_negative(self) -> None:
        with pytest.raises(BlockSpecError, match="decimals must be >= 0"):
            Display(decimals=-1)

    def test_record_appends_samples(self) -> None:
        d = Display(id="d")
        d.record(0.1, np.array([3.14]))
        d.record(0.2, np.array([2.71]))
        assert d.times == [0.1, 0.2]
        np.testing.assert_allclose(d.values, [[3.14], [2.71]])

    def test_latest_returns_last_sample(self) -> None:
        d = Display()
        assert d.latest is None  # データなし
        d.record(0.0, np.array([1.0]))
        d.record(0.1, np.array([2.0]))
        np.testing.assert_array_equal(d.latest, [2.0])

    def test_reset_clears_state(self) -> None:
        d = Display()
        d.record(0.0, np.array([1.0]))
        d.reset()
        assert d.times == []
        assert d.values.shape == (0, 1)
        assert d.latest is None

    def test_simulation_records_correctly(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=42.0))
        d = sim.add(Display(id="d"))
        sim.connect(c, d)
        sim.run()
        assert len(d.times) > 0
        np.testing.assert_allclose(d.latest, [42.0])

    def test_multiple_inputs(self) -> None:
        d = Display(n_inputs=3, labels=["a", "b", "c"])
        assert d.n_inputs == 3
        assert d.labels == ["a", "b", "c"]
        d.record(0.0, np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(d.latest, [1.0, 2.0, 3.0])

    def test_persistence_round_trip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Display(n_inputs=2, decimals=5, labels=["x", "y"], id="d"))
        path = tmp_path / "display.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        d2 = sim2.get_block("d")
        assert d2.n_inputs == 2
        assert d2.decimals == 5
        assert d2.labels == ["x", "y"]


# ---------------------------------------------------------------------------
# XYGraph
# ---------------------------------------------------------------------------


class TestXYGraph:
    def test_default_shape(self) -> None:
        xy = XYGraph()
        assert xy.n_inputs == 2
        assert xy.n_outputs == 0
        assert xy.x_label == "x"
        assert xy.y_label == "y"
        assert xy.labels == ["x", "y"]

    def test_custom_labels(self) -> None:
        xy = XYGraph(x_label="time", y_label="voltage")
        assert xy.labels == ["time", "voltage"]

    def test_record_appends(self) -> None:
        xy = XYGraph()
        xy.record(0.0, np.array([1.0, 10.0]))
        xy.record(0.1, np.array([2.0, 20.0]))
        np.testing.assert_allclose(xy.values, [[1.0, 10.0], [2.0, 20.0]])

    def test_simulation_records_xy_pairs(self) -> None:
        """Sine(0) を x、Sine(π/2 phase) を y に繋ぐと単位円が描ける。"""
        sim = Simulator(t_end=2 * np.pi, dt=0.1)
        sx = sim.add(Sine(amplitude=1.0, frequency=1.0, phase=0.0, id="sx"))
        sy = sim.add(Sine(amplitude=1.0, frequency=1.0, phase=np.pi / 2, id="sy"))
        xy = sim.add(XYGraph(id="xy"))
        sim.connect(sx, xy, dst_idx=0)
        sim.connect(sy, xy, dst_idx=1)
        sim.run()
        v = xy.values
        # x^2 + y^2 ≈ 1 (= 単位円)
        radii = np.sqrt(v[:, 0] ** 2 + v[:, 1] ** 2)
        np.testing.assert_allclose(radii, np.ones_like(radii), atol=1e-9)

    def test_persistence_round_trip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(XYGraph(x_label="theta", y_label="omega", id="xy"))
        path = tmp_path / "xy.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        xy2 = sim2.get_block("xy")
        assert xy2.x_label == "theta"
        assert xy2.y_label == "omega"

    def test_reset(self) -> None:
        xy = XYGraph()
        xy.record(0.0, np.array([1.0, 2.0]))
        xy.reset()
        assert xy.times == []
        assert xy.values.shape == (0, 2)


# ---------------------------------------------------------------------------
# Server registry: Display / XYGraph が登録されている (palette 表示)
# ---------------------------------------------------------------------------


class TestRegistryIncludesNewSinks:
    def test_display_in_registry(self) -> None:
        from pyflw.server.registry import build_block_registry

        reg = build_block_registry()
        type_paths = {m.type_path for m in reg}
        assert "pyflw.blocks.sinks.Display" in type_paths
        assert "pyflw.blocks.sinks.XYGraph" in type_paths

    def test_display_is_in_sinks_category(self) -> None:
        from pyflw.server.registry import build_block_registry

        reg = build_block_registry()
        d = next(m for m in reg if m.type_path == "pyflw.blocks.sinks.Display")
        assert d.category == "sinks"
        assert d.default_n_inputs == 1
        assert d.default_n_outputs == 0
        assert "sink" in d.tags

    def test_xygraph_is_in_sinks_category(self) -> None:
        from pyflw.server.registry import build_block_registry

        reg = build_block_registry()
        xy = next(m for m in reg if m.type_path == "pyflw.blocks.sinks.XYGraph")
        assert xy.category == "sinks"
        assert xy.default_n_inputs == 2
        assert xy.default_n_outputs == 0


# ---------------------------------------------------------------------------
# Display + Gain pipeline (= 中間値の live モニタ用途)
# ---------------------------------------------------------------------------


def test_display_after_gain_shows_amplified_value() -> None:
    sim = Simulator(t_end=0.05, dt=0.01)
    c = sim.add(Constant(value=2.0))
    g = sim.add(Gain(k=3.5))
    d = sim.add(Display(id="d"))
    sim.connect(c, g)
    sim.connect(g, d)
    sim.run()
    np.testing.assert_allclose(d.latest, [7.0])
