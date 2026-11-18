"""Subsystem 内部の手動分岐点 (``params.branch_waypoints``) を持つモデルの読み込み回帰テスト。

GUI は Subsystem の中で置いた手動分岐点を、その Subsystem の ``params.branch_waypoints`` に
書く (ADR-0057)。backend はこれを取り除かずに ``Subsystem._from_dict(**params)`` へ渡して
いたため、未知の引数で ``TypeError`` → ``ModelLoadError`` になり、実行も型解決もできなかった。
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from flode import Simulator, Subsystem
from flode.exceptions import ModelLoadError

_WAYPOINTS = {"g:0": [{"x": 10.0, "y": 20.0}]}


def _inner(k: object) -> dict:
    return {
        "id": "inner",
        "type": "flode.subsystems.subsystem.Subsystem",
        "params": {
            "blocks": [
                {"id": "i", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
                {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": k}},
                {"id": "o", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
            ],
            "connections": [
                {"src": "i", "src_idx": 0, "dst": "g", "dst_idx": 0},
                {"src": "g", "src_idx": 0, "dst": "o", "dst_idx": 0},
            ],
        },
    }


def _outer(inner: dict, *, masked: bool) -> dict:
    params: dict = {
        "blocks": [
            {"id": "i", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
            inner,
            {"id": "o", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
        ],
        "connections": [
            {"src": "i", "src_idx": 0, "dst": "inner", "dst_idx": 0},
            {"src": "inner", "src_idx": 0, "dst": "o", "dst_idx": 0},
        ],
    }
    if masked:
        params["mask_params"] = [{"name": "Kp", "type": "float", "default": 1.0}]
        params["mask_values"] = {"Kp": 3.0}
    return {"id": "outer", "type": "flode.subsystems.subsystem.Subsystem", "params": params}


def _model(outer: dict) -> dict:
    return {
        "schema_version": "0.15",
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
            outer,
            {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
        ],
        "connections": [
            {"src": "c", "src_idx": 0, "dst": "outer", "dst_idx": 0},
            {"src": "outer", "src_idx": 0, "dst": "sc", "dst_idx": 0},
        ],
        "branch_waypoints": {"c:0": [{"x": 1.0, "y": 2.0}]},
    }


@pytest.mark.parametrize(
    ("masked", "k", "expected"),
    [(False, 2.0, 2.0), (True, "$Kp", 3.0)],
    ids=["plain", "masked_outer"],
)
@pytest.mark.parametrize("where", ["outer", "inner", "both"])
def test_subsystem_with_branch_waypoints_loads_and_runs(
    masked: bool, k: object, expected: float, where: str
) -> None:
    inner = _inner(k)
    outer = _outer(inner, masked=masked)
    if where in ("inner", "both"):
        inner["params"]["branch_waypoints"] = copy.deepcopy(_WAYPOINTS)
    if where in ("outer", "both"):
        outer["params"]["branch_waypoints"] = {"inner:0": [{"x": 5.0, "y": 6.0}]}

    sim = Simulator.from_dict(_model(outer))
    sim.run()

    np.testing.assert_allclose(sim.get_block("sc").values[:, 0], expected)
    assert isinstance(sim.get_block("outer"), Subsystem)


def test_from_dict_does_not_mutate_input_with_branch_waypoints() -> None:
    """取り除くのは構築用の写しだけで、呼び出し側の dict (GUI の round-trip 元) は変えない。"""
    inner = _inner(2.0)
    inner["params"]["branch_waypoints"] = copy.deepcopy(_WAYPOINTS)
    data = _model(_outer(inner, masked=False))
    before = copy.deepcopy(data)

    Simulator.from_dict(data)

    assert data == before


def test_unknown_subsystem_param_is_still_rejected() -> None:
    """GUI 専用キー以外の未知の引数 (typo 等) は今までどおり読み込みエラーにする。"""
    outer = _outer(_inner(2.0), masked=False)
    outer["params"]["blokcs"] = []

    with pytest.raises(ModelLoadError):
        Simulator.from_dict(_model(outer))
