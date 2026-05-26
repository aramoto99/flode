"""ADR-0058 §論点 3: Trigger / Enable を Simulator 直下に置くと build 時に reject。

control block は Subsystem 内部にのみ意味を持つ境界ブロック。root 配置は早期 fail
で BlockSpecError を出す (= silent no-op で隠さない)。
"""

from __future__ import annotations

import pytest

from pyflw import Simulator
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems import Enable, Trigger


def test_trigger_at_root_rejected() -> None:
    sim = Simulator(t_end=0.1, dt=0.01)
    sim.add(Trigger(trigger_type="rising", id="root_trig"))
    with pytest.raises(BlockSpecError, match="Trigger.*root level"):
        sim.run()


def test_enable_at_root_rejected() -> None:
    sim = Simulator(t_end=0.1, dt=0.01)
    sim.add(Enable(id="root_en"))
    with pytest.raises(BlockSpecError, match="Enable.*root level"):
        sim.run()
