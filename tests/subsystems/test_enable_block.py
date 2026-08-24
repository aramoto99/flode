"""ADR-0058 §論点 4 / 5: ``Enable`` control block の単体テスト。

Subsystem 内部の境界ブロックとして配置することで親 Subsystem の有効化セマンティクスを
修飾する。本テストは Enable 単体の構築 / validation / param policy のみを検証する
(= 親 Subsystem 統合 / state freeze / output policy の実挙動は Chunk B の Subsystem
統合テストで担保)。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode.exceptions import BlockSpecError
from flode.subsystems.control_blocks import (
    ENABLE_OUTPUT_POLICIES,
    ENABLE_STATE_POLICIES,
    Enable,
)


class TestEnableConstruction:
    """``Enable.__init__`` の引数検証と内部状態。"""

    def test_default_policies_are_held(self) -> None:
        """default は両 policy とも ``"held"`` (ADR-0058 §論点 4 / 5)。"""
        e = Enable()
        assert e.states_when_enabling == "held"
        assert e.outputs_when_disabled == "held"
        assert e._params == {
            "states_when_enabling": "held",
            "outputs_when_disabled": "held",
        }

    @pytest.mark.parametrize("policy", ["held", "reset"])
    def test_explicit_states_when_enabling(self, policy: str) -> None:
        e = Enable(states_when_enabling=policy)  # type: ignore[arg-type]
        assert e.states_when_enabling == policy
        assert e._params["states_when_enabling"] == policy

    @pytest.mark.parametrize("policy", ["held", "reset"])
    def test_explicit_outputs_when_disabled(self, policy: str) -> None:
        e = Enable(outputs_when_disabled=policy)  # type: ignore[arg-type]
        assert e.outputs_when_disabled == policy
        assert e._params["outputs_when_disabled"] == policy

    def test_both_policies_combined(self) -> None:
        e = Enable(states_when_enabling="reset", outputs_when_disabled="reset")
        assert e.states_when_enabling == "reset"
        assert e.outputs_when_disabled == "reset"

    def test_invalid_states_policy_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="states_when_enabling"):
            Enable(states_when_enabling="invalid")  # type: ignore[arg-type]

    def test_invalid_outputs_policy_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="outputs_when_disabled"):
            Enable(outputs_when_disabled="invalid")  # type: ignore[arg-type]

    def test_id_accepted(self) -> None:
        e = Enable(id="en0")
        assert e.id == "en0"

    def test_zero_ports_and_no_state(self) -> None:
        """境界ブロックなので n_inputs = n_outputs = n_states = 0。"""
        e = Enable()
        assert e.n_inputs == 0
        assert e.n_outputs == 0
        assert e.n_states == 0
        assert e.direct_feedthrough is False

    def test_output_returns_empty_ndarray(self) -> None:
        e = Enable()
        out = e.output(0.0, np.zeros(0), np.zeros(0))
        assert out.shape == (0,)


class TestEnableParamEnums:
    """``_param_enums`` 機構で registry が両 policy の enum 値を露出する。"""

    def test_param_enums_exposes_both_policies(self) -> None:
        assert Enable._param_enums == {
            "states_when_enabling": ENABLE_STATE_POLICIES,
            "outputs_when_disabled": ENABLE_OUTPUT_POLICIES,
        }

    def test_both_policies_have_held_and_reset(self) -> None:
        assert set(ENABLE_STATE_POLICIES) == {"held", "reset"}
        assert set(ENABLE_OUTPUT_POLICIES) == {"held", "reset"}


class TestEnableKeywordOnlyArgs:
    """``Enable`` の policy 引数は keyword-only (= positional 渡しを禁止)。"""

    def test_positional_args_rejected(self) -> None:
        # `Enable("reset")` のような positional 渡しは TypeError
        with pytest.raises(TypeError):
            Enable("reset")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 追補: 境界値・エッジケース・同値分割
# ---------------------------------------------------------------------------


class TestEnableIDValidation:
    """``Enable`` の id 引数バリデーション (``validate_block_id`` 経由)。"""

    def test_empty_id_rejected(self) -> None:
        # 空文字 id は BlockSpecError を出す
        with pytest.raises(BlockSpecError):
            Enable(id="")

    def test_id_with_space_rejected(self) -> None:
        # スペースを含む id は文字集合違反
        with pytest.raises(BlockSpecError):
            Enable(id="my enable")

    def test_id_starting_with_digit_rejected(self) -> None:
        # 数字始まりは Python identifier 規則違反
        with pytest.raises(BlockSpecError):
            Enable(id="1enable")

    def test_id_too_long_rejected(self) -> None:
        # 65 文字超は max length 超過
        long_id = "a" * 65
        with pytest.raises(BlockSpecError):
            Enable(id=long_id)

    def test_id_max_length_accepted(self) -> None:
        # 64 文字ちょうどは許可される
        max_id = "e" * 64
        e = Enable(id=max_id)
        assert e.id == max_id

    def test_id_with_non_ascii_accepted(self) -> None:
        # ADR-0071: 非 ASCII (Unicode 識別子) は valid。記号・空白は引き続き拒否
        e = Enable(id="en_α")
        assert e.id == "en_α"
        with pytest.raises(BlockSpecError):
            Enable(id="en α")


class TestEnableNameIdMutualExclusion:
    """``name`` と ``id`` を両方指定すると ``BlockSpecError``。"""

    def test_name_and_id_both_raises(self) -> None:
        # Block 基底クラスの相互排他チェック
        with pytest.raises(BlockSpecError, match="id and name cannot both be set"):
            Enable(id="en0", name="en0")  # type: ignore[call-overload]


class TestEnableParamsIndependence:
    """複数 instance 間で ``_params`` 辞書が共有されていないこと。"""

    def test_params_dict_not_shared_between_instances(self) -> None:
        # 各 instance が独立した _params を持つ
        e1 = Enable(states_when_enabling="held")
        e2 = Enable(states_when_enabling="reset")
        assert e1._params is not e2._params

    def test_mutating_one_params_does_not_affect_other(self) -> None:
        # 一方の _params を書き換えても他方に影響しない
        e1 = Enable()
        e2 = Enable()
        e1._params["states_when_enabling"] = "reset"
        assert e2._params["states_when_enabling"] == "held"


class TestEnableMultipleInstances:
    """複数 Enable instance が互いに干渉しないこと。"""

    @pytest.mark.parametrize(
        "swe, owd",
        [
            ("held", "held"),
            ("held", "reset"),
            ("reset", "held"),
            ("reset", "reset"),
        ],
    )
    def test_all_policy_combinations_independent(self, swe: str, owd: str) -> None:
        # 全 policy 組み合わせを同時生成しても干渉しない
        e = Enable(states_when_enabling=swe, outputs_when_disabled=owd)  # type: ignore[arg-type]
        assert e.states_when_enabling == swe
        assert e.outputs_when_disabled == owd


class TestEnablePickle:
    """``pickle`` / ``copy.deepcopy`` で Enable が複製可能か (persistence 経路)。"""

    def test_pickle_roundtrip(self) -> None:
        import pickle

        # pickle.dumps/loads で属性が保持される
        e = Enable(states_when_enabling="reset", outputs_when_disabled="held", id="en_pkl")
        data = pickle.dumps(e)
        restored = pickle.loads(data)
        assert restored.states_when_enabling == "reset"
        assert restored.outputs_when_disabled == "held"
        assert restored.id == "en_pkl"
        assert restored._params == {
            "states_when_enabling": "reset",
            "outputs_when_disabled": "held",
        }

    def test_deepcopy(self) -> None:
        import copy

        # deepcopy で _params が独立したオブジェクトになる
        e = Enable(states_when_enabling="reset")
        e_copy = copy.deepcopy(e)
        assert e_copy.states_when_enabling == "reset"
        assert e_copy._params is not e._params  # 独立したオブジェクト


class TestEnableOutputShapeDefensive:
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
        e = Enable()
        out = e.output(0.0, np.zeros(x_shape), np.zeros(u_shape))
        assert out.shape == (0,)


class TestEnableParamEnumsRef:
    """``_param_enums`` の値がクラス属性として同一オブジェクトを参照し続ける。"""

    def test_param_enums_same_object_across_instances(self) -> None:
        # _param_enums はクラス変数なので全 instance で同一オブジェクト
        e1 = Enable()
        e2 = Enable(states_when_enabling="reset")
        assert e1._param_enums is e2._param_enums
        assert e1._param_enums is Enable._param_enums

    def test_policy_tuples_are_immutable(self) -> None:
        # ENABLE_STATE_POLICIES / ENABLE_OUTPUT_POLICIES は tuple (immutable)
        assert isinstance(ENABLE_STATE_POLICIES, tuple)
        assert isinstance(ENABLE_OUTPUT_POLICIES, tuple)
