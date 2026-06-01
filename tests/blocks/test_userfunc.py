"""SPEC-0009 / ADR-0059 (v5.2.0): Fcn (User-Defined Function) の網羅テスト。

カバー範囲:
- 構築時検証 (型、長さ、syntax、n_inputs)
- 許可式 (算術 / 比較 / 論理 / IfExp / 許可関数 / u[i] / t)
- セキュリティ拒否 (import / attribute / lambda / comp / dunder / __import__ /
  globals / 代入 / 関数定義 / 未定義名 / u 以外の subscript)
- DoS 上限 (文字列長 / AST node 数 / 深さ / ** 指数)
- 評価エラー (log(-1) → nan / 1/0 → BlockEvalError / u 範囲外 / inf)
- ステートレス (同一 t 多重評価)
- save / load round-trip
- registry / i18n 翻訳テーブル
- 統合: Sine → Fcn (非線形補償) → Scope
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Fcn, Scope, Sine
from pyflw.blocks.userfunc import (
    _MAX_AST_DEPTH,
    _MAX_AST_NODES,
    _MAX_EXPR_LEN,
    _MAX_POW_EXPONENT,
)
from pyflw.core.persistence import CURRENT_SCHEMA_VERSION
from pyflw.exceptions import BlockEvalError, BlockSpecError, ModelLoadError

_EMPTY_X = np.array([])


def _out(blk: Fcn, *u_vals: float, t: float = 0.0) -> float:
    """``output()`` を呼んでスカラー結果を ``float`` で返す。"""
    y = blk.output(t, _EMPTY_X, np.array(u_vals, dtype=float))
    return float(y[0])


# ===========================================================================
# Construction & validation
# ===========================================================================


class TestFcnConstruction:
    def test_default_is_identity(self) -> None:
        blk = Fcn()
        assert blk.expression == "u[0]"
        assert blk.n_inputs == 1
        assert blk.n_outputs == 1
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk._params == {"expression": "u[0]", "n_inputs": 1}
        assert _out(blk, 3.0) == pytest.approx(3.0)

    def test_custom_expression_and_n_inputs(self) -> None:
        blk = Fcn(expression="u[0] + u[1]", n_inputs=2)
        assert blk.expression == "u[0] + u[1]"
        assert blk.n_inputs == 2

    def test_non_str_expression_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="expression must be a str"):
            Fcn(expression=123)  # type: ignore[arg-type]

    def test_negative_n_inputs_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n_inputs must be"):
            Fcn(n_inputs=-1)

    def test_bool_n_inputs_raises(self) -> None:
        """bool は int 派生だが、n_inputs として受け取らない (静的型ヒント整合)。"""
        with pytest.raises(BlockSpecError, match="n_inputs must be"):
            Fcn(n_inputs=True)  # type: ignore[arg-type]

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="syntax error"):
            Fcn(expression="u[0 +")


# ===========================================================================
# Allowed expressions
# ===========================================================================


class TestFcnAllowedExpressions:
    @pytest.mark.parametrize(
        "expr, u, expected",
        [
            ("u[0] + u[1]", (3.0, 4.0), 7.0),
            ("u[0] * u[1]", (3.0, 4.0), 12.0),
            ("u[0] - u[1]", (3.0, 4.0), -1.0),
            ("u[0] / u[1]", (10.0, 4.0), 2.5),
            ("u[0] // u[1]", (10.0, 3.0), 3.0),
            ("u[0] % u[1]", (10.0, 3.0), 1.0),
            ("u[0]**2", (3.0,), 9.0),
            ("-u[0]", (3.0,), -3.0),
        ],
    )
    def test_arithmetic(self, expr: str, u: tuple[float, ...], expected: float) -> None:
        blk = Fcn(expression=expr, n_inputs=len(u))
        assert _out(blk, *u) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "expr, u_val, expected",
        [
            ("sin(u[0])", 0.0, 0.0),
            ("cos(u[0])", 0.0, 1.0),
            ("exp(u[0])", 0.0, 1.0),
            ("sqrt(u[0])", 4.0, 2.0),
            ("abs(u[0])", -3.0, 3.0),
            ("log(u[0])", math.e, 1.0),
        ],
    )
    def test_unary_funcs(self, expr: str, u_val: float, expected: float) -> None:
        blk = Fcn(expression=expr)
        assert _out(blk, u_val) == pytest.approx(expected)

    def test_clip_function(self) -> None:
        blk = Fcn(expression="clip(u[0], 0, 10)")
        assert _out(blk, 15.0) == pytest.approx(10.0)
        assert _out(blk, -5.0) == pytest.approx(0.0)
        assert _out(blk, 5.0) == pytest.approx(5.0)

    def test_min_max_funcs(self) -> None:
        blk_min = Fcn(expression="min(u[0], u[1])", n_inputs=2)
        blk_max = Fcn(expression="max(u[0], u[1])", n_inputs=2)
        assert _out(blk_min, 3.0, 4.0) == pytest.approx(3.0)
        assert _out(blk_max, 3.0, 4.0) == pytest.approx(4.0)

    def test_atan2(self) -> None:
        blk = Fcn(expression="atan2(u[0], u[1])", n_inputs=2)
        assert _out(blk, 1.0, 1.0) == pytest.approx(math.pi / 4)

    def test_t_access(self) -> None:
        blk = Fcn(expression="t * 2")
        assert _out(blk, 0.0, t=3.5) == pytest.approx(7.0)

    def test_n_inputs_zero_source_like(self) -> None:
        """`n_inputs=0` で `t` のみの式はソース的ブロックとして動作する。"""
        blk = Fcn(expression="sin(t) * 2", n_inputs=0)
        assert blk.n_inputs == 0
        y = blk.output(math.pi / 2, _EMPTY_X, np.array([]))
        assert float(y[0]) == pytest.approx(2.0)

    def test_ternary(self) -> None:
        blk = Fcn(expression="u[0] if u[0] > 0 else -u[0]")
        assert _out(blk, 3.0) == pytest.approx(3.0)
        assert _out(blk, -3.0) == pytest.approx(3.0)

    def test_compare_to_indicator(self) -> None:
        blk = Fcn(expression="1.0 if u[0] >= 0 else 0.0")
        assert _out(blk, 0.5) == pytest.approx(1.0)
        assert _out(blk, -0.5) == pytest.approx(0.0)

    def test_boolop_and_or(self) -> None:
        blk = Fcn(expression="(u[0] > 0) and (u[0] < 10)", n_inputs=1)
        # bool は Python int 1/0 にキャストされて float 化される
        assert _out(blk, 5.0) == pytest.approx(1.0)
        assert _out(blk, 15.0) == pytest.approx(0.0)

    def test_unary_not(self) -> None:
        blk = Fcn(expression="not (u[0] > 0)")
        assert _out(blk, 5.0) == pytest.approx(0.0)
        assert _out(blk, -5.0) == pytest.approx(1.0)


# ===========================================================================
# Security rejection (★ 三重防御の検証)
# ===========================================================================


class TestFcnSecurityRejection:
    """脅威モデル: ``.flw.json`` 経由で攻撃式が流れてもサーバプロセスを保護。"""

    @pytest.mark.parametrize(
        "expr",
        [
            "import os",
            "from os import system",
            "y = u[0]",
            "u[0] = 1",
            "def f(): return 1",
            "for i in range(10): i",
            "while True: 1",
        ],
    )
    def test_statement_rejected_at_compile(self, expr: str) -> None:
        """三重防御 (1): ``compile(mode='eval')`` で statement を構文 reject。"""
        with pytest.raises(BlockSpecError, match="syntax error"):
            Fcn(expression=expr)

    @pytest.mark.parametrize(
        "expr, node_name",
        [
            ("lambda x: x", "Lambda"),
            ("[i for i in range(10)]", "ListComp"),
            ("{i for i in range(10)}", "SetComp"),
            ("{i: i for i in range(10)}", "DictComp"),
            ("(i for i in range(10))", "GeneratorExp"),
            ("(1).__class__", "Attribute"),
            ("u[0:2]", "Slice"),
            ("f'{u[0]}'", "JoinedStr"),
            # security-reviewer SHOULD-1 (2026-06-01): walrus / Starred / keyword
            ("(x := u[0])", "NamedExpr"),
            ("sin(*u)", "Starred"),
            ("clip(u[0], min=0, max=10)", "keyword"),
        ],
    )
    def test_disallowed_ast_node_rejected(self, expr: str, node_name: str) -> None:
        """三重防御 (2): AST whitelist で禁止ノード型を reject。"""
        with pytest.raises(BlockSpecError, match=f"disallowed AST node '{node_name}'"):
            Fcn(expression=expr)

    @pytest.mark.parametrize(
        "expr, name",
        [
            ("__import__('os')", "__import__"),
            ("globals()", "globals"),
            ("locals()", "locals"),
            ("eval('1')", "eval"),
            ("open('/etc/passwd')", "open"),
            ("object", "object"),
            ("x", "x"),
            ("True_value", "True_value"),
        ],
    )
    def test_undefined_name_rejected(self, expr: str, name: str) -> None:
        """三重防御 (2 + 3): 許可 Name 以外を構築時 reject (builtins 復元の遮断)。"""
        with pytest.raises(BlockSpecError, match=f"undefined name '{name}'"):
            Fcn(expression=expr)

    def test_subscript_on_non_u_rejected(self) -> None:
        """``u`` 以外への subscript を reject (= ``globals[0]`` 等の escape 経路を塞ぐ)。
        本式では ``globals`` 自体が undefined name で先に reject されるため、構文的に
        到達可能な独立ケースとして ``sin[0]`` (許可関数への subscript) を試す。"""
        with pytest.raises(BlockSpecError, match="subscript only allowed on 'u'"):
            Fcn(expression="sin[0]")

    @pytest.mark.parametrize(
        "expr",
        [
            "u[0][0]",   # chained subscript: u[0] の戻り値への subscript
            "(u + u)[0]",  # BinOp 結果への subscript
            "(-u)[0]",   # UnaryOp 結果への subscript
        ],
    )
    def test_non_name_subscript_target_rejected(self, expr: str) -> None:
        """security-reviewer SHOULD-1: subscript の target が単純な ``Name(id='u')``
        でなければ reject (= 計算結果への subscript 経路を塞ぐ)。"""
        with pytest.raises(BlockSpecError, match="subscript only allowed on 'u'"):
            Fcn(expression=expr)

    def test_dunder_via_attribute_blocked(self) -> None:
        """``__subclasses__`` 等を attribute access で取りに行く経路の遮断。"""
        with pytest.raises(BlockSpecError, match="disallowed AST node 'Attribute'"):
            Fcn(expression="object.__subclasses__()")

    def test_string_constant_rejected(self) -> None:
        """code-reviewer SHOULD-2: 文字列リテラルは構築時に reject (実用性なし、
        三重防御の「構築時に検証済」原則を保つ)。"""
        with pytest.raises(BlockSpecError, match="disallowed constant type 'str'"):
            Fcn(expression="'hello'")


# ===========================================================================
# DoS limits
# ===========================================================================


class TestFcnDoSLimits:
    def test_expression_length_limit(self) -> None:
        long_expr = "u[0]" + " + 0" * 300  # > 1000 chars
        assert len(long_expr) > _MAX_EXPR_LEN
        with pytest.raises(BlockSpecError, match="expression length"):
            Fcn(expression=long_expr)

    def test_ast_node_count_limit(self) -> None:
        # ``+ 0`` を多数連結して node 数を超過させる
        expr = "u[0]" + " + 0" * (_MAX_AST_NODES // 2)  # 各 BinOp + Constant で 3 node
        with pytest.raises(BlockSpecError, match="AST node count"):
            Fcn(expression=expr)

    def test_ast_depth_limit(self) -> None:
        # 左辺ネストで深さを稼ぐ: ((((u[0] + 1) + 1) + 1) + 1)...
        expr = "u[0]" + " + 1" * (_MAX_AST_DEPTH + 5)
        with pytest.raises(BlockSpecError, match=r"AST (node count|depth)"):
            Fcn(expression=expr)

    def test_pow_exponent_limit(self) -> None:
        with pytest.raises(BlockSpecError, match=f"exponent .* exceeds limit {_MAX_POW_EXPONENT}"):
            Fcn(expression=f"u[0]**{_MAX_POW_EXPONENT + 1}")

    def test_pow_exponent_at_limit_ok(self) -> None:
        # 上限ピッタリは OK
        Fcn(expression=f"u[0]**{_MAX_POW_EXPONENT}")


# ===========================================================================
# Evaluation behavior (runtime errors and propagation)
# ===========================================================================


class TestFcnEvaluation:
    def test_log_negative_returns_nan(self) -> None:
        """numpy 関数経由のドメイン外は nan 伝播 (ADR-0053 寛容方針)。"""
        blk = Fcn(expression="log(u[0])")
        with np.errstate(invalid="ignore"):
            assert math.isnan(_out(blk, -1.0))

    def test_pure_python_division_by_zero_raises(self) -> None:
        """純 Python 定数の 0 除算 (numpy を介さない) は ZeroDivisionError → BlockEvalError。"""
        blk = Fcn(expression="1.0 / 0")
        with pytest.raises(BlockEvalError, match="division by zero"):
            _out(blk, 1.0)

    def test_numpy_division_by_zero_returns_inf(self) -> None:
        """numpy scalar の 0 除算は ADR-0053 寛容方針で ±inf を伝播 (例外なし)。"""
        blk = Fcn(expression="u[0] / 0")
        assert _out(blk, 1.0) == float("inf")
        assert _out(blk, -1.0) == float("-inf")

    def test_u_out_of_range_raises(self) -> None:
        blk = Fcn(expression="u[5]", n_inputs=1)
        with pytest.raises(BlockEvalError, match="out of bounds"):
            _out(blk, 1.0)

    def test_inf_input_propagates(self) -> None:
        blk = Fcn(expression="u[0] * 2")
        assert _out(blk, float("inf")) == float("inf")
        assert _out(blk, float("-inf")) == float("-inf")

    def test_nan_input_propagates(self) -> None:
        blk = Fcn(expression="u[0] + 1")
        assert math.isnan(_out(blk, float("nan")))

    def test_error_message_carries_block_id_and_name(self) -> None:
        blk = Fcn(expression="1.0 / 0", name="bad_div")
        with pytest.raises(BlockEvalError) as excinfo:
            _out(blk, 1.0)
        assert "bad_div" in str(excinfo.value)
        assert excinfo.value.block_id == blk.id

    def test_boolop_with_numpy_array_wraps(self) -> None:
        """security-reviewer SHOULD-2: numpy array が混じった BoolOp は
        runtime で例外 → BlockEvalError でラップ (evaluation failed もしくは
        非スカラ result の検出パス)。"""
        # n_inputs=2 として u (= ndarray) を直接 BoolOp に投入
        blk = Fcn(expression="(u[0] > 0) and u", n_inputs=2)
        with pytest.raises(BlockEvalError, match=r"(evaluation failed|result is not scalar)"):
            _out(blk, 1.0, 2.0)


# ===========================================================================
# Stateless
# ===========================================================================


class TestFcnStateless:
    def test_repeated_output_same_value(self) -> None:
        blk = Fcn(expression="u[0]**2 + sin(t)")
        results = [_out(blk, 2.0, t=1.0) for _ in range(10)]
        assert all(r == results[0] for r in results)


# ===========================================================================
# Persistence
# ===========================================================================


class TestFcnPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(
            Fcn(
                expression="u[0] * (1 + 0.05 * u[0]**2)",
                n_inputs=1,
                id="compensator",
            )
        )
        path = tmp_path / "model.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("compensator")
        assert isinstance(loaded, Fcn)
        assert loaded.expression == "u[0] * (1 + 0.05 * u[0]**2)"
        assert loaded.n_inputs == 1

    def test_load_with_attack_expression_raises_model_load_error(
        self, tmp_path: Path
    ) -> None:
        """``.flw.json`` 経由で流入した攻撃式はロード時に ``ModelLoadError`` で実行前拒否。"""
        bad_payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {},
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": 0.01,
            },
            "blocks": [
                {
                    "id": "attacker",
                    "type": "pyflw.blocks.userfunc.Fcn",
                    "params": {
                        "expression": "__import__('os').system('echo pwned')",
                        "n_inputs": 1,
                    },
                }
            ],
            "connections": [],
        }
        path = tmp_path / "attack.flw.json"
        path.write_text(json.dumps(bad_payload))
        with pytest.raises(ModelLoadError, match="Cannot instantiate block") as excinfo:
            Simulator.load(path)
        # AST whitelist が攻撃式を拒否した形跡 (Attribute or undefined name どちら経由でも合格)
        msg = str(excinfo.value)
        assert "disallowed AST node" in msg or "undefined name" in msg


# ===========================================================================
# Registry & i18n
# ===========================================================================


class TestFcnRegistry:
    def test_translation_entry_exists(self) -> None:
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["pyflw.blocks.userfunc.Fcn"]
        assert entry["ja"]["display_name"] == "数式ブロック"
        assert entry["en"]["display_name"] == "Fcn"

    def test_registry_metadata_entry(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["pyflw.blocks.userfunc.Fcn"]
        assert cat == "userfunc"
        assert name == "Fcn"
        assert icon == "userfunc.fcn"


# ===========================================================================
# Integration in Simulator
# ===========================================================================


class TestFcnInModel:
    def test_sine_through_nonlinear_compensator(self, tmp_path: Path) -> None:
        """Sine 入力を Fcn で非線形補償し save/load round-trip。"""

        def build_sim() -> Simulator:
            sim = Simulator(t_end=1.0, dt=0.01)
            sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
            sim.add(
                Fcn(
                    expression="u[0] * (1 + 0.1 * u[0]**2)",
                    n_inputs=1,
                    id="compensator",
                )
            )
            sim.add(Scope(n_inputs=1, id="out"))
            sim.connect("src", "compensator")
            sim.connect("compensator", "out")
            return sim

        sim1 = build_sim()
        sim1.run()
        y1 = np.asarray(sim1.get_block("out").values)[:, 0].copy()

        path = tmp_path / "compensator.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        sim2.run()
        y2 = np.asarray(sim2.get_block("out").values)[:, 0]

        np.testing.assert_allclose(y1, y2, rtol=1e-12)
        # 線形成分 + 3 次成分 → 振幅は ±1 を少し超える
        assert np.max(y2) > 1.0
        assert np.max(y2) < 1.2
