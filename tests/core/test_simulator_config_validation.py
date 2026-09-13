"""``Simulator`` のソルバー設定 (dt / rtol / atol / dt_base) を構築時に検証することの回帰テスト。

2026-09-13 発見: ``rtol <= 0`` は scipy が毎ステップ警告を出しながら ``100*eps`` に
黙って丸め (極端に遅い積分になる)、``atol < 0`` は scipy の生の ``ValueError`` が
run() の途中で飛んでいた。``t_end`` は ``parse_t_end`` で構築時に検証されるのに、
他の設定は run() まで (あるいは scipy まで) 検証されなかった。
"""

from __future__ import annotations

import math

import pytest

from flode import Simulator
from flode.blocks import Constant, Integrator, Scope
from flode.exceptions import ModelLoadError


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dt": 0.0},
        {"dt": -0.1},
        {"dt": math.nan},
        {"dt": math.inf},
        {"rtol": 0.0},
        {"rtol": -1e-3},
        {"rtol": math.nan},
        {"atol": -1e-9},
        # atol=0 は scipy 上は合法だが、状態 0 から始まる積分でステップ幅が 0 に
        # 収束して事実上停止する (300 s 以上) ため flode では拒否する
        {"atol": 0.0},
        {"atol": math.nan},
        {"dt_base": 0.0},
        {"dt_base": -0.01},
    ],
)
def test_invalid_solver_settings_are_rejected_at_construction(kwargs: dict) -> None:
    with pytest.raises(ModelLoadError, match="Invalid"):
        Simulator(t_end=1.0, **kwargs)


def test_tiny_positive_tolerances_run() -> None:
    sim = Simulator(t_end=0.1, dt=0.01, rtol=1e-6, atol=1e-15)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(Integrator(id="i"))
    sim.add(Scope(id="s"))
    sim.connect("c", "i")
    sim.connect("i", "s")
    sim.run()
    assert sim.get_block("s").values[-1, 0] == pytest.approx(0.1, abs=1e-9)


def test_from_dict_rejects_invalid_rtol_as_model_load_error() -> None:
    data = {
        "schema_version": "0.13",
        "simulator": {
            "t_end": 1.0,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 0.0,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [],
        "connections": [],
    }
    with pytest.raises(ModelLoadError):
        Simulator.from_dict(data)
