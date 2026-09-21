"""ADR-0079 Stage 3 (SPEC-0031 #18): ``Constant`` / ``RandomSource`` のベクトル値。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant, Demux, Gain, RandomSource, Scope
from flode.core.signals import has_shape_source
from flode.exceptions import BlockSpecError


class TestConstantVector:
    def test_scalar_value_unchanged(self) -> None:
        c = Constant(value=2.5)
        assert c.value == 2.5 and isinstance(c.value, float)
        assert c.port_shapes_out == ((),)
        assert c._params == {"value": 2.5}
        assert np.array_equal(c.output(0.0, np.zeros(0), np.zeros(0)), np.array([2.5]))
        (y,) = c.output_v(0.0, np.zeros(0), ())
        assert y.shape == () and float(y) == 2.5

    def test_array_value_declares_shape(self) -> None:
        c = Constant(value=[1.0, 2.0, 3.0])
        assert c.port_shapes_out == ((3,),)
        assert c._params == {"value": [1.0, 2.0, 3.0]}
        (y,) = c.output_v(0.0, np.zeros(0), ())
        np.testing.assert_array_equal(y, [1.0, 2.0, 3.0])
        m = Constant(value=[[1.0, 2.0], [3.0, 4.0]])
        assert m.port_shapes_out == ((2, 2),)

    def test_array_value_with_dtype(self) -> None:
        c = Constant(value=[1.7, -2.2], dtype="int32")
        (y,) = c.output_v(0.0, np.zeros(0), ())
        assert y.dtype == np.int32
        np.testing.assert_array_equal(y, [1, -2])

    def test_non_numeric_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="numeric"):
            Constant(value="abc")

    def test_is_shape_source(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=[1.0, 2.0]))
        assert has_shape_source(sim)
        sim2 = Simulator(t_end=0.1, dt=0.01)
        sim2.add(Constant(value=1.0))
        assert not has_shape_source(sim2)

    def test_round_trip_and_no_port_shapes_in_json(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=[1.0, 2.0, 3.0], id="c"))
        path = tmp_path / "c.flw.json"
        sim.save(path)
        entry = next(
            b for b in json.loads(path.read_text(encoding="utf-8"))["blocks"] if b["id"] == "c"
        )
        assert entry["params"] == {"value": [1.0, 2.0, 3.0]}
        assert "port_shapes_out" not in entry
        c2 = Simulator.load(path).get_block("c")
        assert c2.port_shapes_out == ((3,),)
        np.testing.assert_array_equal(c2.value, [1.0, 2.0, 3.0])

    def test_vector_constant_through_gain_matches_demux_expansion(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=[1.0, -2.0, 0.5]))
        g = sim.add(Gain(k=3.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, g)
        sim.connect(g, sc)
        sim.run()
        values = np.asarray(sc.values)
        assert values.shape[1] == 3
        np.testing.assert_array_equal(values[-1], [3.0, -6.0, 1.5])

        sim2 = Simulator(t_end=0.05, dt=0.01)
        c2 = sim2.add(Constant(value=[1.0, -2.0, 0.5]))
        d = sim2.add(Demux(n=3))
        sc2 = sim2.add(Scope(n_inputs=3))
        sim2.connect(c2, d)
        for i in range(3):
            gi = sim2.add(Gain(k=3.0))
            sim2.connect(d, gi, src_idx=i)
            sim2.connect(gi, sc2, dst_idx=i)
        sim2.run()
        assert np.array_equal(np.asarray(sc2.values), values)


class TestRandomSourceShape:
    def test_default_shape_is_scalar_and_series_unchanged(self) -> None:
        rs = RandomSource(sample_time=0.1, seed=7)
        assert rs.shape == () and rs.n_states == 1
        assert rs.port_shapes_out == ((),)
        assert "shape" not in rs._params
        rng = np.random.default_rng(7)
        expected = [rng.uniform(0.0, 1.0) for _ in range(3)]
        rs.reset()
        x = rs.x0
        drawn = []
        for _ in range(3):
            x = rs.advance(0.0, x, np.zeros(0))
            drawn.append(float(x[0]))
        assert drawn == expected

    def test_vector_shape_draws_size_shape(self) -> None:
        rs = RandomSource(sample_time=0.1, seed=7, shape=(3,))
        assert rs.n_states == 3
        assert rs.port_shapes_out == ((3,),)
        assert rs._params["shape"] == [3]
        rs.reset()
        x = rs.advance_v(0.0, rs.x0, ())
        expected = np.random.default_rng(7).uniform(0.0, 1.0, size=(3,))
        np.testing.assert_array_equal(x, expected)
        (y,) = rs.output_v(0.0, x, ())
        assert y.shape == (3,)

    def test_gaussian_matrix_shape(self) -> None:
        rs = RandomSource(sample_time=0.1, seed=1, distribution="gaussian", shape=(2, 2))
        rs.reset()
        x = rs.advance_v(0.0, rs.x0, ())
        expected = np.random.default_rng(1).normal(0.0, 1.0, size=(2, 2)).ravel()
        np.testing.assert_array_equal(x, expected)

    @pytest.mark.parametrize("bad", [(0,), (-1,), (2.0,), "3", (True,)])
    def test_invalid_shape_rejected(self, bad: object) -> None:
        with pytest.raises(BlockSpecError, match="shape"):
            RandomSource(sample_time=0.1, shape=bad)  # type: ignore[arg-type]

    def test_run_records_columns_and_round_trips(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.3, dt=0.1)
        rs = sim.add(RandomSource(sample_time=0.1, seed=3, shape=(2,), id="rs"))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(rs, sc)
        sim.run()
        values = np.asarray(sc.values)
        assert values.shape[1] == 2
        assert np.all((values >= 0.0) & (values < 1.0))
        path = tmp_path / "rs.flw.json"
        sim.save(path)
        rs2 = Simulator.load(path).get_block("rs")
        assert rs2.shape == (2,)
        assert rs2.port_shapes_out == ((2,),)
