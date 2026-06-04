"""ADR-0058 §論点 10: ``Trigger`` control block の単体テスト。

Subsystem 内部の境界ブロックとして配置することで親 Subsystem の発火セマンティクスを
修飾する。本テストは Trigger 単体の構築 / validation / ``is_trigger_edge`` の
edge 検出ロジックのみを検証する (= 親 Subsystem 統合は Chunk B のテストで担保)。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pyflw.exceptions import BlockSpecError
from pyflw.subsystems.control_blocks import (
    TRIGGER_TYPES,
    Trigger,
    is_trigger_edge,
)


class TestTriggerConstruction:
    """``Trigger.__init__`` の引数検証と内部状態。"""

    def test_default_trigger_type_is_rising(self) -> None:
        t = Trigger()
        assert t.trigger_type == "rising"
        assert t._params == {"trigger_type": "rising"}

    @pytest.mark.parametrize("trigger_type", ["rising", "falling", "either", "function-call"])
    def test_explicit_trigger_type_accepted(self, trigger_type: str) -> None:
        t = Trigger(trigger_type=trigger_type)  # type: ignore[arg-type]
        assert t.trigger_type == trigger_type
        assert t._params == {"trigger_type": trigger_type}

    def test_invalid_trigger_type_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="trigger_type"):
            Trigger(trigger_type="invalid")  # type: ignore[arg-type]

    def test_id_accepted(self) -> None:
        t = Trigger(id="trig0")
        assert t.id == "trig0"

    def test_zero_ports_and_no_state(self) -> None:
        """境界ブロックなので n_inputs = n_outputs = n_states = 0。"""
        t = Trigger()
        assert t.n_inputs == 0
        assert t.n_outputs == 0
        assert t.n_states == 0
        assert t.direct_feedthrough is False

    def test_output_returns_empty_ndarray(self) -> None:
        """境界ブロックの ``output()`` は形式上 0-length ndarray を返す。"""
        t = Trigger()
        out = t.output(0.0, np.zeros(0), np.zeros(0))
        assert out.shape == (0,)


class TestTriggerParamEnums:
    """``_param_enums`` 機構 (ADR-0039 follow-up) で registry が enum 値を露出する。"""

    def test_param_enums_exposes_trigger_types(self) -> None:
        assert Trigger._param_enums == {"trigger_type": TRIGGER_TYPES}

    def test_trigger_types_includes_function_call(self) -> None:
        """``"function-call"`` は MVP では構築 OK だが build 時に NotImplementedError
        になる予定 (Chunk B の Subsystem 統合で実装)。本 Chunk A では受け皿だけ用意。"""
        assert "function-call" in TRIGGER_TYPES


class TestIsTriggerEdgeRising:
    """``is_trigger_edge`` の rising mode 判定 (ADR-0036 §(4) semantics 継承)。"""

    def test_zero_to_positive_is_edge(self) -> None:
        assert is_trigger_edge(0.0, 1.0, "rising") is True

    def test_negative_to_positive_is_edge(self) -> None:
        assert is_trigger_edge(-1.0, 1.0, "rising") is True

    def test_positive_to_positive_no_edge(self) -> None:
        assert is_trigger_edge(1.0, 2.0, "rising") is False

    def test_positive_to_zero_no_edge(self) -> None:
        assert is_trigger_edge(1.0, 0.0, "rising") is False

    def test_negative_to_zero_no_edge(self) -> None:
        # zero は positive ではないので edge 検出しない
        assert is_trigger_edge(-1.0, 0.0, "rising") is False


class TestIsTriggerEdgeFalling:
    """``is_trigger_edge`` の falling mode 判定。"""

    def test_zero_to_negative_is_edge(self) -> None:
        assert is_trigger_edge(0.0, -1.0, "falling") is True

    def test_positive_to_negative_is_edge(self) -> None:
        assert is_trigger_edge(1.0, -1.0, "falling") is True

    def test_negative_to_negative_no_edge(self) -> None:
        assert is_trigger_edge(-1.0, -2.0, "falling") is False

    def test_negative_to_zero_no_edge(self) -> None:
        # zero は negative ではないので edge 検出しない
        assert is_trigger_edge(-1.0, 0.0, "falling") is False


class TestIsTriggerEdgeEither:
    """``is_trigger_edge`` の either mode 判定。"""

    def test_rising_edge_detected(self) -> None:
        assert is_trigger_edge(-1.0, 1.0, "either") is True

    def test_falling_edge_detected(self) -> None:
        assert is_trigger_edge(1.0, -1.0, "either") is True

    def test_no_edge_returns_false(self) -> None:
        assert is_trigger_edge(1.0, 2.0, "either") is False
        assert is_trigger_edge(-1.0, -2.0, "either") is False


class TestIsTriggerEdgeNaNSentinel:
    """初回 step の NaN sentinel は edge 扱いしない (= false positive 防止)。"""

    @pytest.mark.parametrize("mode", ["rising", "falling", "either"])
    def test_nan_prev_never_triggers(self, mode: str) -> None:
        assert is_trigger_edge(math.nan, 1.0, mode) is False
        assert is_trigger_edge(math.nan, -1.0, mode) is False
        assert is_trigger_edge(math.nan, 0.0, mode) is False


class TestIsTriggerEdgeInvalidMode:
    """``"function-call"`` や未知の mode は ``is_trigger_edge`` の対象外
    (= edge 検出経路を通らない、build 時に別経路で扱われる)。"""

    def test_function_call_raises_block_spec_error(self) -> None:
        # 旧 _is_trigger_edge と例外型を揃える (BlockSpecError)
        with pytest.raises(BlockSpecError, match="unknown mode"):
            is_trigger_edge(0.0, 1.0, "function-call")

    def test_unknown_mode_raises_block_spec_error(self) -> None:
        with pytest.raises(BlockSpecError, match="unknown mode"):
            is_trigger_edge(0.0, 1.0, "unknown")


# ---------------------------------------------------------------------------
# 追補: 境界値・エッジケース・同値分割
# ---------------------------------------------------------------------------


class TestIsTriggerEdgeBoundaryZero:
    """``prev`` または ``curr`` が 0.0 ちょうどのとき各 mode が正しく判定する。

    Python / IEEE-754 では +0.0 == -0.0 なので signed-zero の挙動も確認する。
    """

    @pytest.mark.parametrize(
        "prev, curr, mode, expected",
        [
            # rising: prev==0 は "0 → positive" なので edge (prev<=0 < curr)
            (0.0, 1e-300, "rising", True),  # 極小の正方向への変化
            (0.0, 1.0, "rising", True),  # 典型ケース (0 → positive)
            (0.0, 0.0, "rising", False),  # prev==curr==0: 変化なし
            (-0.0, 1.0, "rising", True),  # -0.0 は +0.0 と等価なので edge
            (0.0, -1.0, "rising", False),  # 0 → negative: rising でない
            # falling: prev==0 は "0 → negative" なので edge (prev>=0 > curr)
            (0.0, -1.0, "falling", True),  # 典型ケース
            (0.0, -1e-300, "falling", True),  # 極小の負方向への変化
            (0.0, 0.0, "falling", False),  # 変化なし
            (-0.0, -1.0, "falling", True),  # -0.0 も >=0 なので edge
            (0.0, 1.0, "falling", False),  # 0 → positive: falling でない
            # either: 0 を境界にして変化があれば edge
            (0.0, 1.0, "either", True),  # 上昇 edge
            (0.0, -1.0, "either", True),  # 下降 edge
            (0.0, 0.0, "either", False),  # 変化なし
        ],
    )
    def test_zero_boundary(self, prev: float, curr: float, mode: str, expected: bool) -> None:
        # 0.0 境界での符号変化は仕様通り検出される
        assert is_trigger_edge(prev, curr, mode) is expected


class TestIsTriggerEdgeExtremeValues:
    """極小値・極大値・無限大での edge 判定。"""

    @pytest.mark.parametrize(
        "prev, curr, mode, expected",
        [
            # 極小値 (非ゼロだが非常に小さい正)
            (1e-300, 1e-299, "rising", False),  # 正 → 正: rising でない
            (-1e-300, 1e-300, "rising", True),  # 負 → 正: rising edge
            # 極大値
            (1e300, 2e300, "rising", False),  # 正 → 正: edge なし
            (-1e300, 1e300, "either", True),  # 極小負 → 極大正
            # 無限大
            (math.inf, 1.0, "falling", False),  # +inf → 正: falling でない (curr>0)
            (-math.inf, 0.0, "rising", False),  # -inf → 0: rising でない (curr は正でない)
            (-math.inf, 1.0, "rising", True),  # -inf → 正: rising edge
            (math.inf, -math.inf, "falling", True),  # +inf → -inf: falling edge
            (-math.inf, math.inf, "either", True),  # 両極: either edge
            (1.0, math.inf, "rising", False),  # 正 → +inf: prev>0 なのでrising でない
        ],
    )
    def test_extreme_values(self, prev: float, curr: float, mode: str, expected: bool) -> None:
        # 極値・無限大でも通常の比較セマンティクスが維持される
        assert is_trigger_edge(prev, curr, mode) is expected


class TestIsTriggerEdgePrevEqCurr:
    """``prev == curr`` (信号不変) は全 mode で edge なし。"""

    @pytest.mark.parametrize(
        "value, mode",
        [
            (1.0, "rising"),
            (-1.0, "rising"),
            (1.0, "falling"),
            (-1.0, "falling"),
            (1.0, "either"),
            (-1.0, "either"),
            (1e-300, "either"),
            (1e300, "either"),
        ],
    )
    def test_unchanged_signal_never_triggers(self, value: float, mode: str) -> None:
        # 信号が変化しなければどの mode でも edge 検出しない
        assert is_trigger_edge(value, value, mode) is False


class TestIsTriggerEdgeCurrNaN:
    """``curr == NaN`` のとき全 mode で edge なし。

    NaN との比較は常に False になるため、``prev <= 0 < nan`` も False となる。
    """

    @pytest.mark.parametrize("mode", ["rising", "falling", "either"])
    @pytest.mark.parametrize(
        "prev",
        [-1.0, 0.0, 1.0],
    )
    def test_nan_curr_never_triggers(self, prev: float, mode: str) -> None:
        # curr が NaN なら IEEE-754 比較がすべて False になり edge 検出しない
        assert is_trigger_edge(prev, math.nan, mode) is False


class TestIsTriggerEdgeNegativeBothSides:
    """負 → 負 の遷移での各 mode の判定 (同値分割: 符号変化なし)。"""

    @pytest.mark.parametrize(
        "prev, curr, mode, expected",
        [
            (-2.0, -1.0, "rising", False),  # 負 → 負 (大きくなる方向): rising でない
            (-1.0, -2.0, "falling", False),  # 負 → 負 (小さくなる方向): falling でない
            (-2.0, -1.0, "either", False),  # 符号変化なし: either でも edge なし
            (-1.0, -2.0, "either", False),  # 同上
        ],
    )
    def test_negative_to_negative(
        self, prev: float, curr: float, mode: str, expected: bool
    ) -> None:
        # 負の値同士の間では符号変化がないので edge 検出しない
        assert is_trigger_edge(prev, curr, mode) is expected


class TestTriggerIDValidation:
    """``Trigger`` の id 引数バリデーション (``validate_block_id`` 経由)。"""

    def test_empty_id_rejected(self) -> None:
        # 空文字 id は validate_block_id が BlockSpecError を出す
        with pytest.raises(BlockSpecError):
            Trigger(id="")

    def test_id_with_space_rejected(self) -> None:
        # スペースを含む id は文字集合違反
        with pytest.raises(BlockSpecError):
            Trigger(id="my trigger")

    def test_id_starting_with_digit_rejected(self) -> None:
        # 数字始まりは Python identifier 規則違反
        with pytest.raises(BlockSpecError):
            Trigger(id="1trigger")

    def test_id_too_long_rejected(self) -> None:
        # 65 文字超は max length 超過
        long_id = "a" * 65
        with pytest.raises(BlockSpecError):
            Trigger(id=long_id)

    def test_id_max_length_accepted(self) -> None:
        # 64 文字ちょうどは許可される
        max_id = "a" * 64
        t = Trigger(id=max_id)
        assert t.id == max_id

    def test_id_with_non_ascii_rejected(self) -> None:
        # 非 ASCII は文字集合違反
        with pytest.raises(BlockSpecError):
            Trigger(id="trig_α")


class TestTriggerNameIdMutualExclusion:
    """``name`` と ``id`` を両方指定すると ``BlockSpecError``。"""

    def test_name_and_id_both_raises(self) -> None:
        # Block 基底クラスの相互排他チェック
        with pytest.raises(BlockSpecError, match="id and name cannot both be set"):
            Trigger(id="trig0", name="trig0")  # type: ignore[call-overload]


class TestTriggerParamsIndependence:
    """複数 instance 間で ``_params`` 辞書が共有されていないこと。"""

    def test_params_dict_not_shared_between_instances(self) -> None:
        # 各 instance が独立した _params を持つ
        t1 = Trigger(trigger_type="rising")
        t2 = Trigger(trigger_type="falling")
        assert t1._params is not t2._params

    def test_mutating_one_params_does_not_affect_other(self) -> None:
        # 一方の _params を書き換えても他方に影響しない
        t1 = Trigger(trigger_type="rising")
        t2 = Trigger(trigger_type="rising")
        t1._params["trigger_type"] = "falling"
        assert t2._params["trigger_type"] == "rising"


class TestTriggerMultipleInstances:
    """複数 Trigger instance が互いに干渉しないこと。"""

    def test_independent_trigger_types(self) -> None:
        # 各 instance が独立した trigger_type を持つ
        instances = [Trigger(trigger_type=tt) for tt in ["rising", "falling", "either"]]
        assert instances[0].trigger_type == "rising"
        assert instances[1].trigger_type == "falling"
        assert instances[2].trigger_type == "either"

    def test_independent_ids(self) -> None:
        # id も独立している
        t1 = Trigger(id="ta")
        t2 = Trigger(id="tb")
        assert t1.id == "ta"
        assert t2.id == "tb"
        assert t1.id != t2.id


class TestTriggerPickle:
    """``pickle`` / ``copy.deepcopy`` で Trigger が複製可能か (persistence 経路)。"""

    def test_pickle_roundtrip(self) -> None:
        import pickle

        # pickle.dumps/loads で同等の instance が復元される
        t = Trigger(trigger_type="falling", id="trig_pkl")
        data = pickle.dumps(t)
        restored = pickle.loads(data)
        assert restored.trigger_type == "falling"
        assert restored.id == "trig_pkl"
        assert restored._params == {"trigger_type": "falling"}

    def test_deepcopy(self) -> None:
        import copy

        # deepcopy で属性が完全に独立したコピーになる
        t = Trigger(trigger_type="either", id="trig_copy")
        t_copy = copy.deepcopy(t)
        assert t_copy.trigger_type == "either"
        assert t_copy._params is not t._params  # 独立したオブジェクト


class TestTriggerOutputShapeDefensive:
    """``output()`` が非ゼロ shape の引数を渡されても 0-length ndarray を返す。"""

    @pytest.mark.parametrize(
        "x_shape, u_shape",
        [
            ((3,), (2,)),
            ((0,), (5,)),
            ((10,), (0,)),
            ((1,), (1,)),
        ],
    )
    def test_output_always_empty(self, x_shape: tuple, u_shape: tuple) -> None:
        # 非ゼロ引数を渡しても常に shape (0,) を返す
        t = Trigger()
        out = t.output(0.0, np.zeros(x_shape), np.zeros(u_shape))
        assert out.shape == (0,)


class TestTriggerParamEnumsRef:
    """``_param_enums`` の値がクラス属性として同一オブジェクトを参照し続ける。"""

    def test_param_enums_same_object_across_instances(self) -> None:
        # _param_enums はクラス変数なので全 instance で同一オブジェクト
        t1 = Trigger()
        t2 = Trigger(trigger_type="falling")
        assert t1._param_enums is t2._param_enums
        assert t1._param_enums is Trigger._param_enums

    def test_trigger_types_constant_tuple(self) -> None:
        # TRIGGER_TYPES は tuple (immutable) であることを確認
        assert isinstance(TRIGGER_TYPES, tuple)
