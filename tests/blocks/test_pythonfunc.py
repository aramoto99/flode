"""SPEC-0023 / ADR-0073: ``PythonFunction`` ブロックのテスト。

受入基準:
  (i)  モデルを開いた (= ``__init__`` / ``Simulator.load``) だけではコードが実行されない
  (ii) policy が禁止なら実行要求時に明示エラー
  (iv) ``@block`` 直接デコレートと ``PythonFunction`` で結果が同一
  (v)  実行時例外 / shape 不一致が block id + 行番号付きで分類される
"""

from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator, block
from flode.blocks import Constant, PythonFunction, Scope, UnitDelay
from flode.blocks.pythonfunc import (
    DEFAULT_CODE,
    compute_python_digest,
    get_python_block_policy,
    iter_python_functions,
    set_python_block_policy,
)
from flode.exceptions import (
    BlockSpecError,
    PythonBlocksDisabledError,
    PythonFunctionEvalError,
    PythonFunctionSourceError,
)
from flode.subsystems import Inport, Outport, Subsystem


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_python_block_policy(allowed=True)


GAIN_CODE = textwrap.dedent(
    """
    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u
    """
)

INTEG_CODE = textwrap.dedent(
    """
    @block(states=1)
    def integ(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])
    """
)

DELAY_CODE = textwrap.dedent(
    """
    @block(states=1, sample_time=0.1)
    def delay(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])
    """
)


def _marker_code(marker: Path) -> str:
    """module レベルで副作用 (ファイル追記) を起こすソース。"""
    return textwrap.dedent(
        f"""
        with open({str(marker)!r}, "a") as _f:
            _f.write("x")

        @block
        def gain(t: float, u: float, *, k: float = 2.0) -> float:
            return k * u
        """
    )


def _step_chain(pf_block, t_end: float = 0.5, dt: float = 0.01) -> Simulator:
    """``Constant(1.0) → pf_block → Scope`` の最小チェーン。"""
    sim = Simulator(t_end=t_end, dt=dt)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(pf_block)
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", pf_block.id)
    sim.connect(pf_block.id, "scope")
    return sim


def _scope_values(sim: Simulator) -> np.ndarray:
    return np.asarray(sim.get_block("scope").values[:, 0])


# ---------------------------------------------------------------------------
# (i) 遅延実行
# ---------------------------------------------------------------------------


class TestLazyExec:
    def test_init_does_not_execute(self, tmp_path):
        marker = tmp_path / "m.txt"
        pf = PythonFunction(code=_marker_code(marker), id="pf")
        assert pf.n_inputs == 1
        assert not marker.exists()
        assert pf._inner is None

    def test_load_does_not_execute_but_run_does(self, tmp_path):
        marker = tmp_path / "m.txt"
        sim = _step_chain(PythonFunction(code=_marker_code(marker), id="pf"))
        path = tmp_path / "model.flw.json"
        sim.save(path)
        assert not marker.exists()

        loaded = Simulator.load(path)
        assert isinstance(loaded.get_block("pf"), PythonFunction)
        assert not marker.exists()

        loaded.run()
        assert marker.read_text() == "x"

    def test_exec_happens_once_per_instance(self, tmp_path):
        marker = tmp_path / "m.txt"
        sim = _step_chain(PythonFunction(code=_marker_code(marker), id="pf"))
        sim.run()
        sim.run()
        assert marker.read_text() == "x"


# ---------------------------------------------------------------------------
# (iv) Python API との parity
# ---------------------------------------------------------------------------


class TestApiParity:
    def test_gain_matches_direct_block(self):
        @block
        def gain(t: float, u: float, *, k: float = 1.0) -> float:
            return k * u

        direct = _step_chain(gain(k=3.0, id="g"))
        direct.run()
        pf = _step_chain(PythonFunction(code=GAIN_CODE, user_params={"k": 3.0}, id="g"))
        pf.run()
        np.testing.assert_array_equal(_scope_values(pf), _scope_values(direct))
        assert _scope_values(pf)[-1] == 3.0

    def test_continuous_integrator_matches_direct_block(self):
        @block(states=1)
        def integ(
            t: float, x: np.ndarray, u: float, *, x0: float = 0.0
        ) -> tuple[float, np.ndarray]:
            return x[0], np.array([u])

        direct = _step_chain(integ(x0=1.0, id="i"), t_end=1.0)
        direct.run()
        pf = _step_chain(
            PythonFunction(code=INTEG_CODE, user_params={"x0": 1.0}, id="i"), t_end=1.0
        )
        pf.run()
        np.testing.assert_array_equal(_scope_values(pf), _scope_values(direct))
        assert _scope_values(pf)[-1] == pytest.approx(2.0, abs=0.02)

    def test_discrete_delay_matches_direct_block(self):
        @block(states=1, sample_time=0.1)
        def delay(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
            return x[0], np.array([u])

        direct = _step_chain(delay(id="d"), t_end=1.0)
        direct.run()
        pf = _step_chain(PythonFunction(code=DELAY_CODE, id="d"), t_end=1.0)
        pf.run()
        np.testing.assert_array_equal(_scope_values(pf), _scope_values(direct))
        assert pf.get_block("d").sample_time == 0.1

    def test_structure_matches_direct_block(self):
        @block(states=1)
        def integ(
            t: float, x: np.ndarray, u: float, *, x0: float = 0.0
        ) -> tuple[float, np.ndarray]:
            return x[0], np.array([u])

        pf = PythonFunction(code=INTEG_CODE)
        d = integ()
        assert (pf.n_inputs, pf.n_outputs, pf.n_states) == (d.n_inputs, d.n_outputs, d.n_states)
        assert pf.direct_feedthrough == d.direct_feedthrough
        assert pf.sample_time == d.sample_time
        assert pf.spec.params_spec == integ._flode_params_spec


# ---------------------------------------------------------------------------
# (ii) hard gate
# ---------------------------------------------------------------------------


class TestTrustBoundary:
    def test_disabled_policy_rejects_at_run(self, tmp_path):
        marker = tmp_path / "m.txt"
        sim = _step_chain(PythonFunction(code=_marker_code(marker), id="pf"))
        set_python_block_policy(
            allowed=False, reason="bound to 0.0.0.0 without --allow-python-blocks"
        )
        with pytest.raises(PythonBlocksDisabledError, match="allow-python-blocks") as ei:
            sim.run()
        assert isinstance(ei.value, BlockSpecError)
        assert ei.value.block_id == "pf"
        assert "0.0.0.0" in str(ei.value)
        assert not marker.exists()

    def test_disabled_policy_still_allows_load(self, tmp_path):
        set_python_block_policy(allowed=False)
        sim = _step_chain(PythonFunction(code=GAIN_CODE, id="pf"))
        path = tmp_path / "m.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        assert loaded.get_block("pf").n_inputs == 1

    def test_policy_roundtrip(self):
        assert get_python_block_policy().allowed is True
        set_python_block_policy(allowed=False, reason="r")
        assert get_python_block_policy() == get_python_block_policy()
        assert get_python_block_policy().reason == "r"


# ---------------------------------------------------------------------------
# 永続化: type は常に PythonFunction、内包 class は漏れない
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_to_dict_and_round_trip(self, tmp_path):
        sim = _step_chain(PythonFunction(code=GAIN_CODE, user_params={"k": 2.0}, id="pf"))
        d = sim.get_block("pf").to_dict()
        assert d["type"] == "flode.blocks.pythonfunc.PythonFunction"
        assert d["params"] == {"code": GAIN_CODE, "user_params": {"k": 2.0}}

        path = tmp_path / "m.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        pf = loaded.get_block("pf")
        assert isinstance(pf, PythonFunction)
        assert pf.code == GAIN_CODE
        assert pf.user_params == {"k": 2.0}
        loaded.run()
        assert _scope_values(loaded)[-1] == 2.0

    def test_generated_class_never_serialized(self, tmp_path):
        sim = _step_chain(PythonFunction(code=GAIN_CODE, id="pf"))
        sim.run()  # _build 済み (= 内包 class が存在する状態)
        path = tmp_path / "m.flw.json"
        sim.save(path)
        text = path.read_text(encoding="utf-8")
        assert "<generated>" not in text
        data = json.loads(text)
        types = {b["type"] for b in data["blocks"]}
        assert "flode.blocks.pythonfunc.PythonFunction" in types
        assert all(t.startswith("flode.") for t in types)


# ---------------------------------------------------------------------------
# 継承 sample_time (-1.0) の転送回帰 (ADR-0073 §論点 3 V4)
# ---------------------------------------------------------------------------


class TestSampleTimeInherit:
    def test_inherited_discrete_delay_runs_in_discrete_mode(self):
        code = textwrap.dedent(
            """
            @block(states=1, sample_time=-1.0)
            def delay(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
                return x[0], np.array([u])
            """
        )
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(UnitDelay(sample_time=0.1, id="ud"))
        sim.add(PythonFunction(code=code, id="pf"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "ud")
        sim.connect("ud", "pf")
        sim.connect("pf", "scope")
        sim.run()
        pf = sim.get_block("pf")
        assert pf._resolved_sample_time == pytest.approx(0.1)
        # 転送を忘れると inner が連続扱い (= update が no-op) になり出力が 0 のまま残る
        assert _scope_values(sim)[-1] == 1.0
        assert _scope_values(sim)[0] == 0.0


# ---------------------------------------------------------------------------
# (v) エラー分類
# ---------------------------------------------------------------------------


class TestErrors:
    def test_runtime_exception_reports_user_line(self):
        code = textwrap.dedent(
            """
            @block
            def bad(t: float, u: float) -> float:
                if t > 0.05:
                    return 1 / 0
                return u
            """
        )
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        with pytest.raises(PythonFunctionEvalError) as ei:
            sim.run()
        err = ei.value
        assert err.block_id == "pf"
        assert err.lineno == 5
        assert "1 / 0" in (err.source_line or "")
        assert "ZeroDivisionError" in str(err)
        assert "<pythonfunction:pf#" in err.user_traceback  # インスタンス一意の擬似ファイル名
        assert "simulator.py" not in err.user_traceback

    def test_module_level_exception_is_block_spec_error(self):
        """SPEC-0023 §6: exec 中 (module レベル / import 失敗) の例外は BlockSpecError。"""
        code = "raise RuntimeError('boom')\n\n@block\ndef f(t: float, u: float) -> float:\n    return u\n"
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        with pytest.raises(
            BlockSpecError, match=r"module-level code failed.*boom.*\(line 1\)"
        ) as ei:
            sim.run()
        assert not isinstance(ei.value, PythonFunctionEvalError)
        assert isinstance(ei.value.__cause__, RuntimeError)
        assert ei.value.block_id == "pf"

    def test_import_failure_is_block_spec_error(self):
        code = "import no_such_module_xyz\n\n@block\ndef f(t: float, u: float) -> float:\n    return u\n"
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        with pytest.raises(BlockSpecError, match="ModuleNotFoundError"):
            sim.run()

    def test_unicode_id_is_normalized_before_analysis(self):
        # NFD の「ガ」(カ + 濁点) は NFC の「ガ」に正規化される (ADR-0071)
        nfd = "ガ"
        pf = PythonFunction(
            code="@block\ndef f(t: float, u: float) -> float:\n    return u", id=nfd
        )
        assert pf.id == "ガ"
        with pytest.raises(PythonFunctionSourceError) as ei:
            PythonFunction(code="def f(t, u):\n    return u\n", id=nfd)
        assert ei.value.block_id == "ガ"

    def test_shape_mismatch_stays_block_spec_error(self):
        code = textwrap.dedent(
            """
            @block
            def two(t: float, u: float) -> float:
                return (u, u)
            """
        )
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        with pytest.raises(BlockSpecError) as ei:
            sim.run()
        assert not isinstance(ei.value, PythonFunctionEvalError)

    def test_missing_required_param_raises_at_build(self):
        code = "@block\ndef g(t: float, u: float, *, k: float) -> float:\n    return k * u\n"
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        with pytest.raises(BlockSpecError, match="missing required parameter"):
            sim.run()

    def test_syntax_error_at_init(self):
        with pytest.raises(PythonFunctionSourceError) as ei:
            PythonFunction(
                code="@block\ndef f(t: float, u: float) -> float\n    return u\n", id="pf"
            )
        assert ei.value.kind == "syntax"
        assert ei.value.block_id == "pf"

    def test_output_before_build_raises(self):
        pf = PythonFunction(code=GAIN_CODE, id="pf")
        with pytest.raises(BlockSpecError, match="not built"):
            pf.output(0.0, np.zeros(0), np.array([1.0]))


# ---------------------------------------------------------------------------
# user_params
# ---------------------------------------------------------------------------


class TestUserParams:
    def test_undeclared_key_dropped_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="flode.blocks.pythonfunc"):
            pf = PythonFunction(code=GAIN_CODE, user_params={"k": 2.0, "zzz": 1}, id="pf")
        assert pf.user_params == {"k": 2.0}
        assert pf._params["user_params"] == {"k": 2.0}
        assert "zzz" in caplog.text

    def test_non_dict_rejected(self):
        with pytest.raises(BlockSpecError, match="user_params must be a dict"):
            PythonFunction(code=GAIN_CODE, user_params=[1, 2], id="pf")  # type: ignore[arg-type]

    def test_x0_param_sets_initial_state(self):
        pf = PythonFunction(code=INTEG_CODE, user_params={"x0": 2.5}, id="pf")
        np.testing.assert_allclose(pf.x0, [0.0])  # _build 前は Block 既定
        pf._build()
        np.testing.assert_allclose(pf.x0, [2.5])

    def test_default_code_is_valid(self):
        pf = PythonFunction()
        assert pf.code == DEFAULT_CODE
        assert (pf.n_inputs, pf.n_outputs, pf.n_states) == (1, 1, 0)
        # v0.51.2: テンプレートは素通しの最小形 (パラメータは UI から追加する)
        assert pf.spec.params_spec == ()


# ---------------------------------------------------------------------------
# soft gate 用 digest / Subsystem 再帰
# ---------------------------------------------------------------------------


def _pf_subsystem(sub_id: str, pf_id: str, code: str) -> Subsystem:
    sub = Subsystem(id=sub_id)
    sub.add(Inport(port_idx=0, id=f"{sub_id}_in"))
    sub.add(PythonFunction(code=code, id=pf_id))
    sub.add(Outport(port_idx=0, id=f"{sub_id}_out"))
    sub.connect(f"{sub_id}_in", pf_id)
    sub.connect(pf_id, f"{sub_id}_out")
    return sub


class TestDigest:
    def test_none_without_python_function(self):
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="c"))
        assert compute_python_digest(sim) is None

    def test_order_independent_and_code_sensitive(self):
        a = Simulator(t_end=0.1, dt=0.01)
        a.add(PythonFunction(code=GAIN_CODE, id="p1"))
        a.add(PythonFunction(code=INTEG_CODE, id="p2"))
        b = Simulator(t_end=0.1, dt=0.01)
        b.add(PythonFunction(code=INTEG_CODE, id="p2"))
        b.add(PythonFunction(code=GAIN_CODE, id="p1"))
        assert compute_python_digest(a) == compute_python_digest(b)
        assert len(compute_python_digest(a) or "") == 64

        c = Simulator(t_end=0.1, dt=0.01)
        c.add(PythonFunction(code=GAIN_CODE + "\n", id="p1"))
        c.add(PythonFunction(code=INTEG_CODE, id="p2"))
        assert compute_python_digest(c) != compute_python_digest(a)

    def test_recurses_into_subsystem(self):
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_pf_subsystem("sub", "pf_in_sub", GAIN_CODE))
        sim.add(PythonFunction(code=GAIN_CODE, id="pf_top"))
        ids = [qid for qid, _ in iter_python_functions(sim.blocks)]
        assert ids == ["sub/pf_in_sub", "pf_top"]
        assert compute_python_digest(sim) is not None


class TestSubsystemIntegration:
    def test_python_function_inside_subsystem_runs(self):
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=3.0, id="src"))
        sim.add(_pf_subsystem("sub", "pf", GAIN_CODE.replace("k: float = 1.0", "k: float = 2.0")))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")
        sim.run()
        np.testing.assert_allclose(_scope_values(sim), 6.0)


class TestSourceFilenameIsolation:
    def test_same_id_blocks_do_not_share_traceback_source(self):
        """同 id (top-level と Subsystem 内部) でも擬似ファイル名がインスタンス一意。"""
        code_a = "@block\ndef f(t: float, u: float) -> float:\n    raise ValueError('AAA')\n"
        code_b = "@block\ndef f(t: float, u: float) -> float:\n    raise ValueError('BBB')  # B\n"
        a = PythonFunction(code=code_a, id="pf")
        b = PythonFunction(code=code_b, id="pf")
        assert a._source_filename != b._source_filename
        a._build()
        b._build()
        with pytest.raises(PythonFunctionEvalError) as ei:
            a.output(0.0, np.zeros(0), np.array([1.0]))
        assert "AAA" in (ei.value.source_line or "")
        assert "BBB" not in (ei.value.source_line or "")


class TestPortNamesProperty:
    def test_properties_without_build(self):
        code = '@block(input_names=("in1", "in2"), output_names=("out",))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        pf = PythonFunction(code=code, id="pf")
        assert pf.input_names == ("in1", "in2")
        assert pf.output_names == ("out",)
        assert pf._inner is None  # exec されていない

    def test_names_survive_run(self):
        code = '@block(input_names=("x",), output_names=("y",))\ndef f(t: float, u: float) -> float:\n    return u\n'
        sim = _step_chain(PythonFunction(code=code, id="pf"))
        sim.run()
        assert sim.get_block("pf").input_names == ("x",)
