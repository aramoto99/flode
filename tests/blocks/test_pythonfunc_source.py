"""SPEC-0023 / ADR-0073 §論点 1, 2-E: ``PythonFunction`` 静的解析器のテスト。

中核は **parity**: ``analyze_source`` (exec なし) の結果が、同じソースを実際に
``exec`` して ``@block`` を直接適用した結果と完全一致すること (受入基準 iv の土台)。
"""

from __future__ import annotations

import textwrap
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import block
from flode.blocks.pythonfunc_source import (
    GENERATED_MODULE_NAME,
    SourceSpec,
    analyze_source,
    source_filename,
)
from flode.exceptions import BlockSpecError, PythonFunctionSourceError


def _exec_structure(code: str) -> tuple[Any, tuple[Any, ...]]:
    """テスト側の参照実装: 実際に exec して生成 class の構造を読む。"""
    ns: dict[str, Any] = {
        "__name__": GENERATED_MODULE_NAME,
        "block": block,
        "np": np,
        "npt": npt,
        "Any": Any,
    }
    exec(compile(code, "<parity>", "exec"), ns)  # noqa: S102 - テスト内の参照実装
    classes = [v for v in ns.values() if isinstance(v, type) and hasattr(v, "_flode_structure")]
    assert len(classes) == 1
    return classes[0]._flode_structure, classes[0]._flode_params_spec


def _assert_parity(code: str) -> SourceSpec:
    code = textwrap.dedent(code)
    spec = analyze_source(code, block_id="pf")
    structure, params_spec = _exec_structure(code)
    assert (spec.n_inputs, spec.n_outputs, spec.n_states) == (
        structure.n_inputs,
        structure.n_outputs,
        structure.n_states,
    )
    assert spec.direct_feedthrough == structure.direct_feedthrough
    assert spec.sample_time == structure.sample_time
    assert spec.params_spec == tuple(params_spec)
    return spec


# ---------------------------------------------------------------------------
# Parity: 関数形 @block の全分岐
# ---------------------------------------------------------------------------


class TestParity:
    def test_siso_combinational_with_default_param(self):
        spec = _assert_parity(
            '''
            @block
            def gain(t: float, u: float, *, k: float = 2.0) -> float:
                """doc"""
                return k * u
            '''
        )
        assert spec.func_name == "gain"
        assert (spec.n_inputs, spec.n_outputs, spec.n_states) == (1, 1, 0)
        assert spec.direct_feedthrough is True
        assert spec.params_spec == (("k", 2.0, float, False),)

    def test_source_without_u(self):
        spec = _assert_parity(
            """
            @block()
            def ramp(t: float) -> float:
                return t
            """
        )
        assert spec.n_inputs == 0

    def test_mimo_tuple_annotations(self):
        spec = _assert_parity(
            """
            @block
            def swap(t: float, u: tuple[float, float, float]) -> tuple[float, float]:
                return u[1], u[0]
            """
        )
        assert (spec.n_inputs, spec.n_outputs) == (3, 2)

    def test_explicit_inputs_outputs_with_ndarray(self):
        spec = _assert_parity(
            """
            @block(inputs=4, outputs=2)
            def f(t: float, u: np.ndarray) -> np.ndarray:
                return u[:2]
            """
        )
        assert (spec.n_inputs, spec.n_outputs) == (4, 2)

    def test_continuous_state(self):
        spec = _assert_parity(
            """
            @block(states=1)
            def integ(t: float, x: np.ndarray, u: float) -> tuple[float, npt.NDArray[Any]]:
                return x[0], np.array([u])
            """
        )
        assert spec.n_states == 1
        assert spec.direct_feedthrough is False
        assert spec.sample_time is None

    def test_continuous_state_explicit_feedthrough(self):
        spec = _assert_parity(
            """
            @block(states=2, direct_feedthrough=True)
            def f(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
                return x[0] + u, np.array([x[1], -x[0]])
            """
        )
        assert spec.direct_feedthrough is True
        assert spec.n_states == 2

    @pytest.mark.parametrize("st", [0.0, 0.1, -1.0])
    def test_sample_time_variants(self, st: float):
        spec = _assert_parity(
            f"""
            @block(states=1, sample_time={st!r})
            def delay(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
                return x[0], np.array([u])
            """
        )
        assert spec.sample_time == st

    def test_required_and_typed_params(self):
        spec = _assert_parity(
            """
            @block
            def f(t: float, u: float, *, a: float, n: int = 3, flag: bool = False, label: str = "x") -> float:
                return u
            """
        )
        assert spec.params_spec == (
            ("a", None, float, True),
            ("n", 3, int, False),
            ("flag", False, bool, False),
            ("label", "x", str, False),
        )

    def test_x0_reserved_param(self):
        spec = _assert_parity(
            """
            @block(states=1)
            def f(t: float, x: np.ndarray, u: float, *, x0: float = 1.0) -> tuple[float, np.ndarray]:
                return x[0], np.array([u])
            """
        )
        assert spec.params_spec == (("x0", 1.0, float, False),)

    def test_no_return_annotation_assumes_one_output(self, caplog):
        spec = _assert_parity(
            """
            @block
            def f(t: float, u: float):
                return u
            """
        )
        assert spec.n_outputs == 1

    def test_numpy_float64_annotation(self):
        spec = _assert_parity(
            """
            @block
            def f(t: float, u: np.float64) -> np.float64:
                return u
            """
        )
        assert (spec.n_inputs, spec.n_outputs) == (1, 1)

    def test_flode_qualified_decorator_and_imports(self):
        spec = _assert_parity(
            """
            import math
            from flode import block

            HELPER = 2.0

            def helper(v):
                return HELPER * v

            @block
            def f(t: float, u: float) -> float:
                return helper(u) + math.pi
            """
        )
        assert spec.func_name == "f"

    def test_name_override_is_literal_kwarg(self):
        spec = _assert_parity(
            """
            @block(name="MyGain")
            def g(t: float, u: float) -> float:
                return u
            """
        )
        assert spec.func_name == "g"


# ---------------------------------------------------------------------------
# 拒否パス (kind / lineno を含む)
# ---------------------------------------------------------------------------


class TestRejections:
    def test_syntax_error_reports_line(self):
        with pytest.raises(PythonFunctionSourceError) as ei:
            analyze_source("@block\ndef f(t: float, u: float) -> float\n    return u\n")
        assert ei.value.kind == "syntax"
        assert ei.value.lineno == 2
        assert isinstance(ei.value, BlockSpecError)

    def test_no_block_function(self):
        with pytest.raises(PythonFunctionSourceError, match="no top-level @block"):
            analyze_source("def f(t, u):\n    return u\n")

    def test_two_block_functions(self):
        code = textwrap.dedent(
            """
            @block
            def a(t: float, u: float) -> float:
                return u

            @block
            def b(t: float, u: float) -> float:
                return u
            """
        )
        with pytest.raises(PythonFunctionSourceError, match="exactly one @block") as ei:
            analyze_source(code)
        assert ei.value.lineno == 7

    def test_class_form_rejected_with_hint(self):
        code = textwrap.dedent(
            """
            @block(states=1)
            class Leaky:
                def output(self, t: float, x: np.ndarray, u: float) -> float:
                    return x[0]
                def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                    return np.array([u])
            """
        )
        with pytest.raises(PythonFunctionSourceError, match="class-form"):
            analyze_source(code)

    def test_non_literal_decorator_argument(self):
        code = "N = 2\n@block(states=N)\ndef f(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:\n    return x[0], np.array([u, u])\n"
        with pytest.raises(PythonFunctionSourceError, match="must be a literal") as ei:
            analyze_source(code)
        assert ei.value.kind == "spec"
        assert ei.value.lineno == 2

    def test_positional_decorator_argument(self):
        with pytest.raises(PythonFunctionSourceError, match="keyword arguments only"):
            analyze_source("@block(1)\ndef f(t: float, u: float) -> float:\n    return u\n")

    def test_unresolved_annotation_mentions_escape_hatch(self):
        code = "Vec = tuple[float, float]\n@block\ndef f(t: float, u: Vec) -> float:\n    return u[0]\n"
        with pytest.raises(PythonFunctionSourceError, match="inputs=N, outputs=M") as ei:
            analyze_source(code)
        # lineno は ``def`` 行 (= シグネチャの位置) を指す
        assert ei.value.lineno == 3

    def test_call_in_annotation_is_never_evaluated(self):
        code = (
            "import os\n"
            "@block\n"
            "def f(t: float, u: os.system('echo pwned')) -> float:\n"
            "    return u\n"
        )
        with pytest.raises(PythonFunctionSourceError, match="cannot resolve type annotation"):
            analyze_source(code)

    def test_non_literal_default(self):
        code = (
            "@block\ndef f(t: float, u: float, *, k: float = np.pi) -> float:\n    return k * u\n"
        )
        with pytest.raises(PythonFunctionSourceError, match="defaults must be literals"):
            analyze_source(code)

    def test_block_inference_error_is_wrapped_with_same_message(self):
        # decorator.py 側の推論エラー文面がそのまま含まれる (= API と同一文面)
        code = "@block\ndef f(t: float, u: np.ndarray) -> float:\n    return u[0]\n"
        with pytest.raises(PythonFunctionSourceError, match="bare ndarray annotation") as ei:
            analyze_source(code)
        with pytest.raises(BlockSpecError, match="bare ndarray annotation"):
            _exec_structure(code)
        assert ei.value.lineno == 2

    def test_star_args_rejected_like_block(self):
        code = "@block\ndef f(t: float, *args) -> float:\n    return 0.0\n"
        with pytest.raises(PythonFunctionSourceError, match=r"cannot have \*args"):
            analyze_source(code)

    def test_async_rejected(self):
        code = "@block\nasync def f(t: float, u: float) -> float:\n    return u\n"
        with pytest.raises(PythonFunctionSourceError, match="async"):
            analyze_source(code)

    def test_non_str_code(self):
        with pytest.raises(PythonFunctionSourceError, match="must be a str"):
            analyze_source(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 「exec しない」ことの直接検証
# ---------------------------------------------------------------------------


class TestNoExecution:
    def test_module_level_side_effect_does_not_fire(self, tmp_path):
        marker = tmp_path / "executed.txt"
        code = textwrap.dedent(
            f"""
            open({str(marker)!r}, "w").write("x")

            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        spec = analyze_source(code, block_id="pf")
        assert spec.n_inputs == 1
        assert not marker.exists()

    def test_source_filename_format(self):
        assert source_filename("pf_1") == "<pythonfunction:pf_1>"
        assert source_filename(None) == "<pythonfunction:unnamed>"


class TestPortNamesInSpec:
    def test_names_readable_without_exec(self, tmp_path):
        marker = tmp_path / "m.txt"
        code = (
            f'open({str(marker)!r}, "w").write("x")\n\n'
            '@block(input_names=("速度指令", ""), output_names=("トルク",))\n'
            "def f(t: float, u: tuple[float, float]) -> float:\n"
            "    return u[0]\n"
        )
        spec = analyze_source(code, block_id="pf")
        assert spec.input_names == ("速度指令", "")
        assert spec.output_names == ("トルク",)
        assert spec.has_u_arg is True
        assert not marker.exists()  # 静的解析だけで exec されない

    def test_defaults_and_has_u_arg_false(self):
        spec = analyze_source("@block\ndef s(t: float) -> float:\n    return t\n")
        assert spec.input_names == ()
        assert spec.output_names == ()
        assert spec.has_u_arg is False

    def test_dsl_violation_is_source_error(self):
        code = '@block(input_names=("a",))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        with pytest.raises(PythonFunctionSourceError, match="must match exactly"):
            analyze_source(code)

    def test_parity_with_exec_for_names(self):
        code = '@block(input_names=("a", "b"))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        spec = analyze_source(code)
        structure, _ = _exec_structure(code)
        assert spec.input_names == structure.input_names
        assert spec.has_u_arg == structure.has_u_arg
