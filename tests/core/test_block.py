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


class _ScalarOutUpdateV(Block):
    """出力はスカラー版、状態更新は ``update_v`` だけ (全ポート ``()``)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            id=id, n_inputs=1, n_outputs=1, n_states=1, sample_time=TS, direct_feedthrough=False
        )
        self.x0 = np.zeros(1)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]

    def update_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return x + float(u[0])


class _ScalarOutAdvanceV(Block):
    """出力はスカラー版、シフト相は ``advance_v`` だけ (全ポート ``()``)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=1, n_states=1, sample_time=TS)
        self.x0 = np.zeros(1)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]

    def advance_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return x + 1.0


class _ScalarOutDerivativeV(Block):
    """連続系。出力はスカラー版、微分は ``derivative_v`` だけ (全ポート ``()``)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=1, n_states=1, direct_feedthrough=False)
        self.x0 = np.zeros(1)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]

    def derivative_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return np.array([float(u[0])])


def _run(block: Block, value: float | list[float], t_end: float = 0.3) -> npt.NDArray[Any]:
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


class TestScalarModelWithVectorStateApiOnly:
    """全スカラーのモデル (SM-A 経路) でも ``_v`` 版だけの状態メソッドが呼ばれる。

    修正前は Block 既定のスカラー版 (``x`` をそのまま返す / ゼロ) が呼ばれ、状態が初期値のまま
    進まなかった (例外にならず、黙って誤った値になる)。
    """

    def test_update_v_only_block_advances_state(self) -> None:
        out = _run(_ScalarOutUpdateV(id="b"), 2.0)
        np.testing.assert_allclose(out, [0.0, 2.0, 4.0, 6.0])

    def test_advance_v_only_block_shifts_state(self) -> None:
        out = _run(_ScalarOutAdvanceV(id="b"), 2.0)
        np.testing.assert_allclose(out, [1.0, 2.0, 3.0, 4.0])

    def test_derivative_v_only_block_integrates(self) -> None:
        out = _run(_ScalarOutDerivativeV(id="b"), 2.0)
        np.testing.assert_allclose(out, [0.0, 0.2, 0.4, 0.6], atol=1e-9)

    @pytest.mark.parametrize(
        ("cls", "method", "expected"),
        # x = 3、u = 4 のとき: update_v は x + u、advance_v は x + 1、derivative_v は u
        [
            (_ScalarOutUpdateV, "update", [7.0]),
            (_ScalarOutAdvanceV, "advance", [4.0]),
            (_ScalarOutDerivativeV, "derivative", [4.0]),
        ],
    )
    def test_scalar_default_delegates_to_v(
        self, cls: type[Block], method: str, expected: list[float]
    ) -> None:
        result = getattr(cls(), method)(0.0, np.array([3.0]), np.array([4.0]))
        np.testing.assert_allclose(result, expected)

    def test_both_overridden_uses_own_scalar_version(self) -> None:
        # スカラー版も書いたブロックでは委譲せず、そのスカラー版が呼ばれる
        block = _ScalarStateApi()
        np.testing.assert_allclose(block.update(0.0, np.array([3.0]), np.array([4.0])), [7.0])


class _WrapperStyle(Block):
    """``_v`` 版の中でスカラー版を呼ぶ書き方 (スカラー版は書かない)。委譲が自分に戻ってくる。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=1, n_outputs=1, n_states=1, sample_time=TS)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]

    def update_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return self.update(t, x, np.array([float(v) for v in u]))

    def advance_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return self.advance(t, x, np.array([float(v) for v in u]))

    def derivative_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return self.derivative(t, x, np.array([float(v) for v in u]))


def _lti_blocks() -> list[Block]:
    """``_v`` 版の中でスカラー版を呼ぶ標準ブロック (LtiVectorPortMixin) の例。"""
    from flode.blocks import DiscreteStateSpace, MimoTransferFunction, StateSpace

    one = np.array([[1.0]])
    return [
        StateSpace(A=-one, B=one, C=one),
        MimoTransferFunction(numerators=[[[1.0]]], denominator=[1.0, 1.0]),
        DiscreteStateSpace(A=one * 0.5, B=one, C=one, sample_time=TS),
        _WrapperStyle(),
    ]


class TestDelegationDoesNotRecurse:
    """スカラー版の既定 → ``_v`` 版 → スカラー版 と戻ってきても無限再帰しない。

    戻ってきた呼び出しは委譲せず Block 既定 (``x`` / ゼロ) を返す (委譲を入れる前と同じ結果)。
    """

    @pytest.mark.parametrize("block", _lti_blocks(), ids=lambda b: type(b).__name__)
    @pytest.mark.parametrize("method", ["update", "advance", "derivative"])
    def test_scalar_method_returns(self, block: Block, method: str) -> None:
        if not block._inherits(method):
            pytest.skip(f"{type(block).__name__} overrides {method}")
        x = np.asarray(block.x0, dtype=float)
        result = getattr(block, method)(0.0, x, np.zeros(block.n_inputs))
        expected = np.zeros(block.n_states) if method == "derivative" else x
        np.testing.assert_array_equal(result, expected)


class _FailsOnce(Block):
    """``update_v`` が 1 回目だけ例外を出す (``update`` は既定)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=1, n_outputs=1, n_states=1, sample_time=TS)
        self.calls = 0

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return x[:1]

    def update_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        self.calls += 1
        if self.calls == 1:
            raise ValueError("first call fails")
        return x + 1.0


def test_delegation_resumes_after_exception() -> None:
    # 例外のあとも委譲中の印が残らず、次の呼び出しで再び update_v が呼ばれる
    block = _FailsOnce()
    with pytest.raises(ValueError, match="first call fails"):
        block.update(0.0, np.zeros(1), np.zeros(1))
    np.testing.assert_allclose(block.update(0.0, np.zeros(1), np.zeros(1)), [1.0])
    assert block.calls == 2
    assert block.__dict__["_delegating_to_v"] == set()
