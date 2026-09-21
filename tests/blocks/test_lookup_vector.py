"""ADR-0079 Stage 3 (SPEC-0031 #18): lookup 5 クラスのベクトル入力。

``Mux → lookup → Demux`` 版と、スカラ n 本を並べた版が bit-identical であること
(スカラ核 ``_eval`` を要素ごとに呼ぶだけなので構造で保証される)。
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Constant,
    Demux,
    InterpolationUsingPrelookup,
    LookupTable1D,
    LookupTable2D,
    LookupTableND,
    Mux,
    Prelookup,
    Scope,
)
from flode.core.block import Block
from flode.exceptions import BlockEvalError

_BP = [0.0, 1.0, 2.0, 3.0]
_TBL = [0.0, 1.0, 4.0, 9.0]


def _lut1d(**kw: object) -> Block:
    return LookupTable1D(breakpoints=_BP, table=_TBL, **kw)  # type: ignore[arg-type]


def _lut2d(**kw: object) -> Block:
    return LookupTable2D(
        breakpoints_row=[0.0, 1.0, 2.0],
        breakpoints_col=[0.0, 1.0],
        table=[[0.0, 1.0], [1.0, 3.0], [4.0, 7.0]],
        **kw,  # type: ignore[arg-type]
    )


def _lutnd(**kw: object) -> Block:
    return LookupTableND(
        breakpoints_axes=[[0.0, 1.0], [0.0, 1.0], [0.0, 2.0]],
        table=np.arange(8, dtype=float).reshape(2, 2, 2).tolist(),
        **kw,  # type: ignore[arg-type]
    )


_INPUTS_1 = np.array([-0.5, 0.25, 1.5, 2.75, 3.5, float("inf"), float("nan")])
_INPUTS_2 = np.array([0.0, 0.5, 1.0, -1.0, 2.5, 0.3, float("nan")])
_INPUTS_3 = np.array([0.0, 1.0, 0.5, 2.0, 3.0, 0.7, 1.1])


def _run_vector(block: Block, inputs: list[np.ndarray]) -> np.ndarray:
    """各入力ポートに Constant(配列) を繋いだベクトル版を 1 ステップ走らせる。"""
    sim = Simulator(t_end=0.01, dt=0.01)
    b = sim.add(block)
    for i, arr in enumerate(inputs):
        sim.connect(sim.add(Constant(value=arr.tolist())), b, dst_idx=i)
    sc = sim.add(Scope(n_inputs=b.n_outputs))
    for j in range(b.n_outputs):
        sim.connect(b, sc, src_idx=j, dst_idx=j)
    sim.run()
    return np.asarray(sc.values)[-1]


def _run_scalar(factory: Callable[[], Block], inputs: list[np.ndarray]) -> np.ndarray:
    """要素ごとにブロックを複製したスカラ版を走らせ、ベクトル版と同じ列順で返す。"""
    n = inputs[0].shape[0]
    sim = Simulator(t_end=0.01, dt=0.01)
    blocks = [sim.add(factory()) for _ in range(n)]
    n_out = blocks[0].n_outputs
    sc = sim.add(Scope(n_inputs=n * n_out))
    for e, b in enumerate(blocks):
        for i, arr in enumerate(inputs):
            sim.connect(sim.add(Constant(value=float(arr[e]))), b, dst_idx=i)
        for j in range(n_out):
            sim.connect(b, sc, src_idx=j, dst_idx=j * n + e)
    sim.run()
    return np.asarray(sc.values)[-1]


@pytest.mark.parametrize("interpolation", ["linear", "nearest", "flat"])
@pytest.mark.parametrize("extrapolation", ["clip", "linear"])
def test_lookup1d_vector_matches_scalar(interpolation: str, extrapolation: str) -> None:
    kw = {"interpolation": interpolation, "extrapolation": extrapolation}
    vec = _run_vector(_lut1d(**kw), [_INPUTS_1])
    sca = _run_scalar(lambda: _lut1d(**kw), [_INPUTS_1])
    np.testing.assert_array_equal(vec, sca)


@pytest.mark.parametrize("interpolation", ["linear", "nearest", "flat"])
@pytest.mark.parametrize("extrapolation", ["clip", "linear"])
def test_lookup2d_vector_matches_scalar(interpolation: str, extrapolation: str) -> None:
    kw = {"interpolation": interpolation, "extrapolation": extrapolation}
    vec = _run_vector(_lut2d(**kw), [_INPUTS_1, _INPUTS_2])
    sca = _run_scalar(lambda: _lut2d(**kw), [_INPUTS_1, _INPUTS_2])
    np.testing.assert_array_equal(vec, sca)


@pytest.mark.parametrize("interpolation", ["linear", "nearest", "flat"])
@pytest.mark.parametrize("extrapolation", ["clip", "linear"])
def test_lookupnd_vector_matches_scalar(interpolation: str, extrapolation: str) -> None:
    kw = {"interpolation": interpolation, "extrapolation": extrapolation}
    ins = [_INPUTS_1, _INPUTS_2, _INPUTS_3]
    vec = _run_vector(_lutnd(**kw), ins)
    sca = _run_scalar(lambda: _lutnd(**kw), ins)
    np.testing.assert_array_equal(vec, sca)


@pytest.mark.parametrize("extrapolation", ["clip", "linear"])
def test_prelookup_two_outputs_vector_matches_scalar(extrapolation: str) -> None:
    vec = _run_vector(Prelookup(breakpoints=_BP, extrapolation=extrapolation), [_INPUTS_1])
    sca = _run_scalar(lambda: Prelookup(breakpoints=_BP, extrapolation=extrapolation), [_INPUTS_1])
    assert vec.shape == (2 * _INPUTS_1.shape[0],)
    np.testing.assert_array_equal(vec, sca)


@pytest.mark.parametrize("interpolation", ["linear", "nearest", "flat"])
def test_interpolation_using_prelookup_vector_matches_scalar(interpolation: str) -> None:
    k = np.array([0.0, 1.0, 2.0, 5.0, -1.0, 1.0, float("nan")])
    f = np.array([0.0, 0.5, 0.25, 0.75, 0.1, 1.5, 0.2])
    vec = _run_vector(InterpolationUsingPrelookup(table=_TBL, interpolation=interpolation), [k, f])
    sca = _run_scalar(
        lambda: InterpolationUsingPrelookup(table=_TBL, interpolation=interpolation), [k, f]
    )
    np.testing.assert_array_equal(vec, sca)


def test_prelookup_to_interpolation_chain_vector() -> None:
    """Prelookup → InterpolationUsingPrelookup をベクトルで繋ぐと LookupTable1D と一致。"""
    x = np.array([0.2, 1.5, 2.9])
    sim = Simulator(t_end=0.01, dt=0.01)
    c = sim.add(Constant(value=x.tolist()))
    pre = sim.add(Prelookup(breakpoints=_BP))
    interp = sim.add(InterpolationUsingPrelookup(table=_TBL))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(c, pre)
    sim.connect(pre, interp, src_idx=0, dst_idx=0)
    sim.connect(pre, interp, src_idx=1, dst_idx=1)
    sim.connect(interp, sc)
    sim.run()
    np.testing.assert_allclose(np.asarray(sc.values)[-1], np.interp(x, _BP, _TBL))


def test_scalar_broadcast_with_vector_input_2d() -> None:
    """2-D lookup の片方がスカラ、もう片方がベクトルでもスカラ拡張で要素ごとに評価される。"""
    sim = Simulator(t_end=0.01, dt=0.01)
    row = sim.add(Constant(value=[0.0, 1.0, 2.0]))
    col = sim.add(Constant(value=1.0))
    lut = sim.add(_lut2d())
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(row, lut, dst_idx=0)
    sim.connect(col, lut, dst_idx=1)
    sim.connect(lut, sc)
    sim.run()
    np.testing.assert_array_equal(np.asarray(sc.values)[-1], [1.0, 3.0, 7.0])


def test_extrapolation_error_raised_per_element() -> None:
    sim = Simulator(t_end=0.01, dt=0.01)
    c = sim.add(Constant(value=[0.5, 10.0]))
    lut = sim.add(_lut1d(extrapolation="error"))
    d = sim.add(Demux(n=2))
    sim.connect(c, lut)
    sim.connect(lut, d)
    with pytest.raises(BlockEvalError, match="outside breakpoints"):
        sim.run()


def test_mux_demux_round_trip_shape() -> None:
    sim = Simulator(t_end=0.01, dt=0.01)
    a = sim.add(Constant(value=0.5))
    b = sim.add(Constant(value=2.5))
    mux = sim.add(Mux(n=2))
    lut = sim.add(_lut1d())
    demux = sim.add(Demux(n=2))
    sc = sim.add(Scope(n_inputs=2))
    sim.connect(a, mux, dst_idx=0)
    sim.connect(b, mux, dst_idx=1)
    sim.connect(mux, lut)
    sim.connect(lut, demux)
    sim.connect(demux, sc, src_idx=0, dst_idx=0)
    sim.connect(demux, sc, src_idx=1, dst_idx=1)
    sim.run()
    np.testing.assert_allclose(np.asarray(sc.values)[-1], [0.5, 6.5])
