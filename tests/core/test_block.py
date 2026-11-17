"""Block の既定の状態 API (``advance_v`` / ``update_v`` / ``derivative_v``) のテスト。"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block, Simulator
from flode.blocks import Constant, Scope
from flode.exceptions import BlockSpecError

TS = 0.1


class _VectorSum(Block):
    """``update_v`` / ``output_v`` だけを書いた離散ブロック (``advance`` は既定のまま)。

    入力ベクトルの合計を状態に足していき、状態を出力する。
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            id=id, n_inputs=1, n_outputs=1, n_states=1, sample_time=TS,
            direct_feedthrough=False, port_shapes_in=((3,),), port_shapes_out=((),),
        )  # fmt: skip
        self.x0 = np.zeros(1)

    def output_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.array(x[0]),)

    def update_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return x + float(np.sum(u[0]))


class _VectorAdvance(Block):
    """``advance_v`` / ``output_v`` だけを書いた離散ブロック (``update`` は既定のまま)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            id=id, n_inputs=1, n_outputs=1, n_states=1, sample_time=TS,
            port_shapes_in=((3,),), port_shapes_out=((),),
        )  # fmt: skip
        self.x0 = np.zeros(1)

    def advance_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return np.array([float(np.max(u[0]))])

    def output_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.array(x[0]),)


class _ScalarStateApi(Block):
    """スカラー版の状態 API をすべて上書きしたブロック (ベクトル入力は明示エラーのまま)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=1, n_outputs=1, n_states=1, sample_time=TS)

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return u[:1]

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x + u[0]

    def advance(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x + u[0]

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]


def _run(block: Block, value: list[float], t_end: float = 0.3) -> npt.NDArray[Any]:
    sim = Simulator(t_end=t_end, dt=TS)
    src = sim.add(Constant(value=value, id="src"))
    blk = sim.add(block)
    sc = sim.add(Scope(id="sc"))
    sim.connect(src, blk)
    sim.connect(blk, sc)
    sim.run()
    return np.asarray(sc.values, dtype=float).ravel()


class TestDefaultStateApiWithVectorInputs:
    """SM-A 版を上書きしていないとき、既定の ``_v`` 版はベクトル入力でも既定の動きをする。"""

    def test_update_v_only_block_runs_with_vector_input(self) -> None:
        # 修正前: 既定の advance_v が入力をスカラーへ変換しようとして BlockSpecError
        out = _run(_VectorSum(id="b"), [1.0, 2.0, 3.0])
        np.testing.assert_allclose(out, [0.0, 6.0, 12.0, 18.0])

    def test_advance_v_only_block_runs_with_vector_input(self) -> None:
        # 修正前: 既定の update_v が入力をスカラーへ変換しようとして BlockSpecError
        out = _run(_VectorAdvance(id="b"), [1.0, 5.0, 2.0])
        np.testing.assert_allclose(out, [5.0, 5.0, 5.0, 5.0])

    @pytest.mark.parametrize("method", ["advance_v", "update_v"])
    def test_default_returns_state_unchanged(self, method: str) -> None:
        block = _VectorSum()
        x = np.array([4.0])
        result = getattr(Block, method)(block, 0.0, x, (np.ones((2, 3)),))
        np.testing.assert_array_equal(result, x)

    def test_default_derivative_v_returns_zeros(self) -> None:
        block = _VectorSum()
        result = block.derivative_v(0.0, np.array([4.0]), (np.ones(3),))
        np.testing.assert_array_equal(result, np.zeros(1))

    @pytest.mark.parametrize("method", ["advance_v", "update_v", "derivative_v"])
    def test_overridden_scalar_api_still_rejects_vector(self, method: str) -> None:
        with pytest.raises(BlockSpecError, match="scalar state API"):
            getattr(_ScalarStateApi(), method)(0.0, np.zeros(1), (np.ones(3),))
