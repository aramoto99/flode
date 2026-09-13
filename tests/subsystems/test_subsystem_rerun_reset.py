"""同一 ``Simulator`` を 2 回 ``run()`` したときの再現性 (Subsystem のキャッシュ reset)。

2026-09-13 発見: ``Subsystem`` に ``reset()`` hook がなく、Trigger の前回値
(``_prev_trigger_value``)・Enable の前回値・出力キャッシュ (``_last_y``) と
内部ブロックの ``reset()`` (RandomSource の RNG 等) が 2 回目の run に持ち越され、
同じ Simulator の再実行結果が初回と一致しなかった。
"""

from __future__ import annotations

import numpy as np

from flode import Enable, Inport, Outport, Simulator, Subsystem, Trigger
from flode.blocks import (
    Gain,
    Integrator,
    LogicalOperator,
    PulseGenerator,
    RandomSource,
    Scope,
    Sine,
)


def _build() -> Simulator:
    sim = Simulator(t_end=2.0, dt=0.01)
    sim.add(Sine(amplitude=1.0, frequency=0.5, id="sine"))
    sim.add(PulseGenerator(period=0.4, pulse_width=50.0, id="pulse"))
    sh = Subsystem(id="sh")
    sh.add(Inport(port_idx=0, id="i"))
    sh.add(Outport(port_idx=0, id="o"))
    sh.add(Trigger(trigger_type="either", id="trig"))
    sh.connect("i", "o")
    sim.add(sh)
    en = Subsystem(id="en")
    en.add(Inport(port_idx=0, id="i"))
    en.add(Integrator(x0=0.0, id="I"))
    en.add(Outport(port_idx=0, id="o"))
    en.add(Enable(outputs_when_disabled="reset", id="e"))
    en.connect("i", "I")
    en.connect("I", "o")
    sim.add(en)
    sim.add(LogicalOperator("NOT", 1, id="not_pulse"))
    # RandomSource を Subsystem の中に置く (内部ブロックの reset 伝搬)
    rs = Subsystem(id="noise")
    rs.add(RandomSource(sample_time=0.1, seed=11, id="rnd"))
    rs.add(Gain(k=0.5, id="g"))
    rs.add(Outport(port_idx=0, id="o"))
    rs.connect("rnd", "g")
    rs.connect("g", "o")
    sim.add(rs)
    sim.add(Scope(n_inputs=3, labels=["sh", "en", "noise"], buffer_mode="unbounded", id="sc"))
    sim.connect("sine", "sh", dst_idx=0)
    sim.connect("pulse", "sh", dst_idx=1)
    sim.connect("pulse", "not_pulse")
    sim.connect("sh", "en", dst_idx=0)
    sim.connect("not_pulse", "en", dst_idx=1)
    sim.connect("sh", "sc", dst_idx=0)
    sim.connect("en", "sc", dst_idx=1)
    sim.connect("noise", "sc", dst_idx=2)
    return sim


def test_second_run_on_same_simulator_is_bit_identical() -> None:
    sim = _build()
    sim.run()
    first = sim.get_block("sc").values.copy()
    sim.run()
    second = sim.get_block("sc").values.copy()
    np.testing.assert_array_equal(first, second)


def test_second_run_matches_fresh_simulator() -> None:
    sim = _build()
    sim.run()
    sim.run()
    fresh = _build()
    fresh.run()
    np.testing.assert_array_equal(sim.get_block("sc").values, fresh.get_block("sc").values)
