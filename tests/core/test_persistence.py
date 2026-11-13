"""ADR-0008 JSON 永続化 (Simulator.save / load) のテスト。

主に round-trip (load(save(sim)) で等価) と例外パスを検証する。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from flode import (
    BlockSpecError,
    ModelLoadError,
    ModelSerializationError,
    SchemaVersionError,
    Simulator,
    UnknownBlockTypeError,
    block,
)
from flode.blocks import (
    Constant,
    DiscreteIntegrator,
    Gain,
    Integrator,
    LogicalOperator,
    PulseGenerator,
    Ramp,
    RelationalOperator,
    Saturation,
    Scope,
    Sine,
    StateSpace,
    Step,
    Sum,
    Switch,
    TransferFunction,
    UnitDelay,
)
from flode.core import persistence as _persistence
from flode.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    block_type_path,
    register_block_module,
    register_migration,
    reset_block_module_allowlist,
    resolve_block_class,
    to_json_value,
)


@pytest.fixture(autouse=True)
def _allow_test_module_blocks():
    """テスト内で生成した ``@block`` 由来の class をロード可能にする allowlist。

    また migration registry をテスト前後でスナップショット → 復元することで、
    テスト間の汚染を防ぐ (組み込み migration は復元される)。
    """
    register_block_module("tests.")
    saved = dict(_persistence._MIGRATIONS)
    try:
        yield
    finally:
        reset_block_module_allowlist()
        _persistence._MIGRATIONS.clear()
        _persistence._MIGRATIONS.update(saved)
        _persistence._register_builtin_migrations()


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------


def _build_spring_mass_damper() -> Simulator:
    """Phase 0 テスト用モデル相当の構築 (検証用にコンパクト化)。"""
    sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-8, atol=1e-10)
    sim.add(Step(step_time=0.0, final_value=1.0, id="F"))
    sim.add(Sum(signs="+--", id="sum"))
    sim.add(Gain(k=1.0, id="inv_m"))
    sim.add(Integrator(x0=0.0, id="x_dot"))
    sim.add(Integrator(x0=0.0, id="x"))
    sim.add(Gain(k=0.5, id="c"))
    sim.add(Gain(k=4.0, id="k"))
    sim.add(Scope(n_inputs=2, labels=["x", "x_dot"], id="response"))
    sim.connect("F", "sum", dst_idx=0)
    sim.connect("c", "sum", dst_idx=1)
    sim.connect("k", "sum", dst_idx=2)
    sim.connect("sum", "inv_m")
    sim.connect("inv_m", "x_dot")
    sim.connect("x_dot", "x")
    sim.connect("x_dot", "c")
    sim.connect("x", "k")
    sim.connect("x", "response", dst_idx=0)
    sim.connect("x_dot", "response", dst_idx=1)
    return sim


# ---------------------------------------------------------------
# JSON 値変換 (to_json_value)
# ---------------------------------------------------------------


class TestToJsonValue:
    def test_scalars(self):
        assert to_json_value(1.5) == 1.5
        assert to_json_value(3) == 3
        assert to_json_value(True) is True
        assert to_json_value("abc") == "abc"
        assert to_json_value(None) is None

    def test_numpy_scalars(self):
        assert to_json_value(np.float64(2.5)) == 2.5
        assert to_json_value(np.int64(7)) == 7
        assert isinstance(to_json_value(np.float64(2.5)), float)
        assert isinstance(to_json_value(np.int64(7)), int)

    def test_numpy_array(self):
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = to_json_value(arr)
        assert result == [[1.0, 2.0], [3.0, 4.0]]
        assert all(isinstance(v, list) for v in result)

    def test_list_and_tuple(self):
        assert to_json_value([1, 2, "x"]) == [1, 2, "x"]
        assert to_json_value((1.0, 2.0)) == [1.0, 2.0]

    def test_nested_dict(self):
        assert to_json_value({"a": 1, "b": {"c": [1.0, 2.0]}}) == {
            "a": 1,
            "b": {"c": [1.0, 2.0]},
        }

    def test_unsupported_raises(self):
        with pytest.raises(ModelSerializationError, match="Cannot serialize"):
            to_json_value(object())


# ---------------------------------------------------------------
# block_type_path / resolve_block_class
# ---------------------------------------------------------------


class TestBlockTypeResolution:
    def test_path_for_standard_block(self):
        assert block_type_path(Gain) == "flode.blocks.mathops.Gain"

    def test_resolve_standard_block(self):
        cls = resolve_block_class("flode.blocks.mathops.Gain")
        assert cls is Gain

    def test_resolve_via_blocks_init(self):
        # `flode.blocks` でも import 可能
        cls = resolve_block_class("flode.blocks.Gain")
        assert cls is Gain

    def test_unknown_module_raises(self):
        # allowlist 経由で `flode.does_not_exist` を試す (default で `flode.*` 許可)
        with pytest.raises(UnknownBlockTypeError, match="Cannot import module"):
            resolve_block_class("flode.does_not_exist.Foo")

    def test_unknown_attribute_raises(self):
        with pytest.raises(UnknownBlockTypeError, match="has no attribute"):
            resolve_block_class("flode.blocks.NoSuchClass")

    def test_non_block_class_raises(self):
        with pytest.raises(UnknownBlockTypeError, match="not a Block subclass"):
            resolve_block_class("flode.exceptions.FlodeError")

    def test_unqualified_name_raises(self):
        with pytest.raises(UnknownBlockTypeError, match="fully-qualified"):
            resolve_block_class("Gain")

    def test_disallowed_module_rejected(self):
        """allowlist に無い module は import 試行前に拒否される (security)。"""
        # `tests.` は autouse fixture で許可済みなので、それ以外を試す
        with pytest.raises(UnknownBlockTypeError, match="not in an allowed module prefix"):
            resolve_block_class("os.system")

    def test_register_block_module_extends_allowlist(self):
        """``register_block_module`` で追加した prefix がロード可能になる。"""
        register_block_module("numpy.")
        # numpy.float64 は class だが Block サブクラスではないので別エラー
        with pytest.raises(UnknownBlockTypeError, match="not a Block subclass"):
            resolve_block_class("numpy.float64")

    def test_namespace_package_under_allowed_prefix_is_rejected(self, tmp_path, monkeypatch):
        """allowlist の prefix 配下でも、``__init__.py`` の無いディレクトリ (namespace
        package) の中のモジュールは import しない。

        prefix の検査は文字列の前方一致だけなので、パッケージのディレクトリに紛れた
        Python ファイル (同梱物や依存ツールが置いたもの) まで import 対象になるのを防ぐ。
        """
        import sys

        marker = tmp_path / "imported.txt"
        package = tmp_path / "nsprobe_pkg"
        (package / "loose").mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "regular.py").write_text("VALUE = 1\n", encoding="utf-8")
        # ``loose`` には __init__.py が無い = namespace package
        (package / "loose" / "payload.py").write_text(
            f"open({str(marker)!r}, 'w').write('imported')\n", encoding="utf-8"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        register_block_module("nsprobe_pkg.")
        try:
            with pytest.raises(UnknownBlockTypeError, match="namespace package"):
                resolve_block_class("nsprobe_pkg.loose.payload.Anything")
            with pytest.raises(UnknownBlockTypeError, match="namespace package"):
                resolve_block_class("nsprobe_pkg.loose.Anything")
            assert not marker.exists()
            assert "nsprobe_pkg.loose.payload" not in sys.modules
            # 通常のパッケージ配下は従来どおり import される (正当な利用を壊さない)
            with pytest.raises(UnknownBlockTypeError, match="has no attribute"):
                resolve_block_class("nsprobe_pkg.regular.Missing")
        finally:
            for name in [m for m in sys.modules if m.split(".")[0] == "nsprobe_pkg"]:
                del sys.modules[name]

    def test_frontend_directory_is_not_importable_as_block_module(self):
        """``flode/web`` は ``__init__.py`` を持たないディレクトリ。配下は解決対象外。"""
        with pytest.raises(UnknownBlockTypeError, match="namespace package"):
            resolve_block_class("flode.web.frontend.Anything")

    @pytest.mark.parametrize("module_name", ["dynblocks_probe", "dynblocks_probe.inner"])
    def test_dynamically_created_module_without_spec_is_resolvable(self, module_name):
        """``__spec__`` が ``None`` のモジュール (スクリプト・notebook・``types.ModuleType`` で
        動的に作ったもの) に定義したブロックは、prefix を登録すれば従来どおり解決できる。

        そうしたモジュールは import 済み (``sys.modules`` にある) で、namespace package では
        ない。``importlib.util.find_spec`` はこの場合 ``ValueError`` を出すので呼ばない。
        """
        import sys
        import types

        names = [
            ".".join(module_name.split(".")[: i + 1]) for i in range(module_name.count(".") + 1)
        ]
        modules = {name: types.ModuleType(name) for name in names}
        assert all(m.__spec__ is None for m in modules.values())
        block_cls = type("DynGain", (Gain,), {"__module__": module_name})
        modules[module_name].DynGain = block_cls
        register_block_module("dynblocks_probe.")
        sys.modules.update(modules)
        try:
            assert resolve_block_class(f"{module_name}.DynGain") is block_cls
        finally:
            for name in names:
                sys.modules.pop(name, None)

    def test_registered_prefix_may_itself_be_a_namespace_distribution(self, tmp_path, monkeypatch):
        """利用者が明示的に登録した prefix を構成する階層は namespace package でもよい
        (PEP 420 の namespace 配布)。検査するのは prefix より下の階層だけ。"""
        import sys

        marker = tmp_path / "imported.txt"
        plugins = tmp_path / "acme_nsprobe" / "plugins"  # どちらも __init__.py 無し
        (plugins / "loose").mkdir(parents=True)
        (plugins / "blocks.py").write_text("VALUE = 1\n", encoding="utf-8")
        (plugins / "loose" / "payload.py").write_text(
            f"open({str(marker)!r}, 'w').write('imported')\n", encoding="utf-8"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        register_block_module("acme_nsprobe.plugins.")
        try:
            # prefix 直下の通常モジュールは import される (クラスが無いので別エラー)
            with pytest.raises(UnknownBlockTypeError, match="has no attribute"):
                resolve_block_class("acme_nsprobe.plugins.blocks.Missing")
            # prefix より下の namespace ディレクトリ配下は import しない
            with pytest.raises(UnknownBlockTypeError, match="namespace package"):
                resolve_block_class("acme_nsprobe.plugins.loose.payload.Anything")
            assert not marker.exists()
            # prefix の外は allowlist が拒否する
            with pytest.raises(UnknownBlockTypeError, match="not in an allowed module prefix"):
                resolve_block_class("acme_nsprobe.other.Anything")
        finally:
            for name in [m for m in sys.modules if m.split(".")[0] == "acme_nsprobe"]:
                del sys.modules[name]

    def test_cached_namespace_package_is_still_rejected(self, tmp_path, monkeypatch):
        """namespace package が既に import 済み (``sys.modules`` にある) でも拒否は変わらない。"""
        import importlib
        import sys

        package = tmp_path / "nscached_pkg"
        (package / "loose").mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "loose" / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        register_block_module("nscached_pkg.")
        try:
            importlib.import_module("nscached_pkg.loose")
            assert "nscached_pkg.loose" in sys.modules
            with pytest.raises(UnknownBlockTypeError, match="namespace package"):
                resolve_block_class("nscached_pkg.loose.payload.Anything")
            assert "nscached_pkg.loose.payload" not in sys.modules
        finally:
            for name in [m for m in sys.modules if m.split(".")[0] == "nscached_pkg"]:
                del sys.modules[name]

    @pytest.mark.parametrize(
        "type_path",
        ["flode..blocks.Gain", "flode.blocks.mathops.", "flode.blo cks.Gain", "flode.1x.Gain"],
    )
    def test_non_identifier_segments_are_rejected(self, type_path):
        with pytest.raises(UnknownBlockTypeError, match="identifier"):
            resolve_block_class(type_path)


# ---------------------------------------------------------------
# Round-trip: load(save(sim)) で等価
# ---------------------------------------------------------------


class TestRoundTrip:
    def test_phase0_spring_mass_damper(self, tmp_path):
        sim = _build_spring_mass_damper()
        path = tmp_path / "model.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)

        assert sim2.t_end == sim.t_end
        assert sim2.dt == sim.dt
        assert sim2.solver == sim.solver
        assert sim2.rtol == sim.rtol
        assert sim2.atol == sim.atol
        assert [b.id for b in sim2.blocks] == [b.id for b in sim.blocks]

        # 実行結果も一致 (同じ初期状態 + 同じソルバー設定)
        sim.run()
        sim2.run()
        scope1 = sim.get_block("response")
        scope2 = sim2.get_block("response")
        np.testing.assert_allclose(scope1.values, scope2.values, rtol=1e-9, atol=1e-12)

    def test_discrete_blocks_round_trip(self, tmp_path):
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(UnitDelay(sample_time=0.01, x0=0.5, id="delay"))
        sim.add(DiscreteIntegrator(sample_time=0.01, gain=2.0, x0=0.0, id="di"))
        sim.add(Scope(n_inputs=2, id="scope"))
        sim.connect("src", "delay")
        sim.connect("delay", "di")
        sim.connect("delay", "scope", dst_idx=0)
        sim.connect("di", "scope", dst_idx=1)

        path = tmp_path / "discrete.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )

    def test_lti_blocks_round_trip(self, tmp_path):
        """LTI ブロック (numpy 行列パラメータ) の round-trip。"""
        sim = Simulator(t_end=0.5, dt=0.01, rtol=1e-9, atol=1e-12)
        sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        sim.add(
            StateSpace(
                A=np.array([[-1.0, 0.0], [0.0, -2.0]]),
                B=np.array([[1.0], [1.0]]),
                C=np.array([[1.0, 1.0]]),
                id="ss",
            )
        )
        sim.add(TransferFunction([1.0], [1.0, 0.4, 1.0], id="tf"))
        sim.add(Scope(n_inputs=2, id="scope"))
        sim.connect("src", "ss")
        sim.connect("src", "tf")
        sim.connect("ss", "scope", dst_idx=0)
        sim.connect("tf", "scope", dst_idx=1)

        path = tmp_path / "lti.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )

    def test_misc_blocks_round_trip(self, tmp_path):
        """様々なブロック種類を含むモデル。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Ramp(slope=1.0, start_time=0.0, id="ramp"))
        sim.add(Sine(amplitude=2.0, frequency=1.0, phase=0.5, id="sine"))
        sim.add(PulseGenerator(amplitude=1.0, period=0.02, pulse_width=50.0, id="pulse"))
        sim.add(Saturation(lower=-1.0, upper=1.0, id="sat"))
        sim.add(RelationalOperator(operator=">", id="rel"))
        sim.add(LogicalOperator(operator="AND", n_inputs=2, id="logic"))
        sim.add(Switch(threshold=0.5, criterion=">=", id="sw"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("ramp", "sat")
        sim.connect("sat", "scope")
        sim.connect("ramp", "rel", dst_idx=0)
        sim.connect("sine", "rel", dst_idx=1)
        sim.connect("rel", "logic", dst_idx=0)
        sim.connect("pulse", "logic", dst_idx=1)
        sim.connect("ramp", "sw", dst_idx=0)
        sim.connect("logic", "sw", dst_idx=1)
        sim.connect("sine", "sw", dst_idx=2)

        path = tmp_path / "misc.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )

    def test_decorated_block_round_trip(self, tmp_path):
        """``@block`` 関数版で生成したカスタムブロックの round-trip。"""

        @block
        def my_doubler(t: float, u: float, *, k: float = 2.0) -> float:
            return k * u

        # __module__ をテスト用に固定 (load 側でも解決可能にする)
        my_doubler.__module__ = "tests.core.test_persistence"

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=3.0, id="src"))
        sim.add(my_doubler(k=4.0, id="dbl"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "dbl")
        sim.connect("dbl", "scope")

        path = tmp_path / "decorated.flw.json"
        sim.save(path)
        # decorated class は test module 名前空間にバインドされているので
        # `tests.core.test_persistence.MyDoubler` で解決可能
        # (`globals()` に MyDoubler が登録されている必要がある)
        globals()["MyDoubler"] = my_doubler

        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )


# ---------------------------------------------------------------
# JSON 出力フォーマット検証
# ---------------------------------------------------------------


class TestJsonFormat:
    def test_required_top_level_keys(self, tmp_path):
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Constant(value=1.0, id="c1"))
        path = tmp_path / "small.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("schema_version", "metadata", "simulator", "blocks", "connections"):
            assert key in data

    def test_schema_version_is_current(self, tmp_path):
        sim = Simulator(t_end=1.0, dt=0.01)
        path = tmp_path / "v.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_block_entry_structure(self, tmp_path):
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Gain(k=2.5, id="g"))
        path = tmp_path / "g.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        block_entry = data["blocks"][0]
        assert block_entry == {
            "id": "g",
            "type": "flode.blocks.mathops.Gain",
            "params": {"k": 2.5},
        }


# ---------------------------------------------------------------
# 例外パス
# ---------------------------------------------------------------


class TestLoadErrors:
    def test_missing_schema_version(self, tmp_path):
        path = tmp_path / "no_version.flw.json"
        path.write_text(json.dumps({"blocks": [], "connections": []}), encoding="utf-8")
        with pytest.raises(ModelLoadError, match="schema_version"):
            Simulator.load(path)

    def test_unsupported_schema_version(self, tmp_path):
        path = tmp_path / "future.flw.json"
        path.write_text(
            json.dumps({"schema_version": "9.99", "blocks": [], "connections": []}),
            encoding="utf-8",
        )
        with pytest.raises(SchemaVersionError, match="9.99"):
            Simulator.load(path)

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "broken.flw.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ModelLoadError, match="Invalid JSON"):
            Simulator.load(path)

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(ModelLoadError, match="Cannot read"):
            Simulator.load(tmp_path / "missing.flw.json")

    def test_top_level_must_be_object(self, tmp_path):
        path = tmp_path / "list.flw.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ModelLoadError, match="must be an object"):
            Simulator.load(path)

    def test_unknown_block_type_raises(self, tmp_path):
        payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [{"id": "x", "type": "flode.blocks.NoSuchBlock", "params": {}}],
            "connections": [],
        }
        path = tmp_path / "unknown.flw.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(UnknownBlockTypeError):
            Simulator.load(path)

    def test_block_init_typeerror_wrapped(self, tmp_path):
        """ブロック ``__init__`` が想定外の TypeError を出したら ModelLoadError。"""
        payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {
                    "id": "g",
                    "type": "flode.blocks.mathops.Gain",
                    "params": {"unknown_param": 1.0},
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad_init.flw.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ModelLoadError, match="Cannot instantiate"):
            Simulator.load(path)


class TestSaveErrors:
    def test_main_module_block_rejected(self, tmp_path):
        """``__module__ == "__main__"`` のブロックは保存できない (ロード不可のため)。"""

        @block
        def main_only(t: float, u: float, *, k: float = 1.0) -> float:
            return k * u

        # @block は __module__ を関数の __module__ から引き継ぐ。
        # 強制的に __main__ にする。
        main_only.__module__ = "__main__"

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(main_only(id="m"))
        sim.connect("src", "m")

        path = tmp_path / "main.flw.json"
        with pytest.raises(ModelSerializationError, match="__main__"):
            sim.save(path)


# ---------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------


class TestMigration:
    def test_register_and_apply(self, tmp_path):
        """登録した migration が呼ばれることを確認 (sentinel)。

        ``_MIGRATIONS`` registry の汚染は ``_allow_test_module_blocks`` fixture が
        テスト後にクリアする。
        """
        called: list[str] = []

        @register_migration("0.0", CURRENT_SCHEMA_VERSION)
        def _migrate(data):
            called.append("migrated")
            data = dict(data)
            data["schema_version"] = CURRENT_SCHEMA_VERSION
            return data

        payload = {
            "schema_version": "0.0",
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [],
            "connections": [],
        }
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        sim = Simulator.load(path)
        assert called == ["migrated"]
        assert sim.t_end == 1.0


# ---------------------------------------------------------------
# Sum.signs (str) のような構造化パラメータ
# ---------------------------------------------------------------


def test_sum_signs_round_trip(tmp_path):
    """``Sum(signs="++-")`` の str パラメータが round-trip で保たれる。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="a"))
    sim.add(Constant(value=2.0, id="b"))
    sim.add(Constant(value=3.0, id="c"))
    sim.add(Sum(signs="++-", id="s"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("a", "s", dst_idx=0)
    sim.connect("b", "s", dst_idx=1)
    sim.connect("c", "s", dst_idx=2)
    sim.connect("s", "scope")

    path = tmp_path / "sum.flw.json"
    sim.save(path)
    sim2 = Simulator.load(path)
    assert sim2.get_block("s").signs.tolist() == [1.0, 1.0, -1.0]


# ---------------------------------------------------------------
# id 衝突の事前検出
# ---------------------------------------------------------------


def test_duplicate_id_in_json_raises(tmp_path):
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "simulator": {
            "t_end": 1.0,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [
            {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 1.0}},
            {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 2.0}},
        ],
        "connections": [],
    }
    path = tmp_path / "dup.flw.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BlockSpecError, match="already exists"):
        Simulator.load(path)


# ---------------------------------------------------------------------------
# モジュールに書いた ``@block`` ブロックの save → load (ADR-0081 U0)
# ---------------------------------------------------------------------------

_DECORATED_BLOCKS_SOURCE = """\
from flode import block


@block
def scaled(t: float, u: float, *, k: float = 2.0) -> float:
    return k * u


@block(port_shapes_in=((3,),), port_shapes_out=((3,),))
def vec_gain(t: float, u: float, *, k: float = 2.0) -> float:
    return k * u


@block
class low_pass:
    tau: float = 1.0

    def output(self, t: float, u: float) -> float:
        return u
"""


@pytest.fixture
def decorated_blocks_module(tmp_path, monkeypatch):
    """``@block`` で書いたブロックを持つ import 可能なモジュール (``decoblocks_probe.blocks``)。"""
    import importlib
    import sys

    package = tmp_path / "decoblocks_probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "blocks.py").write_text(_DECORATED_BLOCKS_SOURCE, encoding="utf-8")
    # 同名のクラスを 2 つ定義して別名で束縛したモジュール (どちらを指すか決められない)
    (package / "ambiguous.py").write_text(
        "from flode.blocks import Gain\n\n"
        "class Twin(Gain):\n    pass\n\nfirst = Twin\n\n"
        "class Twin(Gain):  # noqa: F811\n    pass\n\nsecond = Twin\ndel Twin\n",
        encoding="utf-8",
    )
    # 別モジュールで定義されたブロックを import して持つだけのモジュール
    (package / "reexport.py").write_text(
        "from decoblocks_probe.blocks import scaled\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    register_block_module("decoblocks_probe.")
    try:
        yield importlib.import_module("decoblocks_probe.blocks")
    finally:
        for name in [m for m in sys.modules if m.split(".")[0] == "decoblocks_probe"]:
            del sys.modules[name]


class TestDecoratedBlockModuleRoundTrip:
    """モジュールに書いた ``@block`` ブロックを使ったモデルを、保存して読み込める。

    回帰: (A) 関数形式 (と PascalCase でない名前のクラス形式) は型名が生成クラス名に
    なるのに、モジュール上には元の名前で束縛されるため、読み込みで型を解決できなかった。
    (B) ``port_shapes_*`` を宣言したブロックは、保存した ``port_shapes_*`` を生成
    クラスの ``__init__`` が受け取れず、読み込みに失敗していた。
    """

    @staticmethod
    def _round_trip(block_obj, tmp_path):
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(block_obj)
        path = tmp_path / "model.flw.json"
        sim.save(path)
        return Simulator.load(path).get_block(block_obj.id), json.loads(
            path.read_text(encoding="utf-8")
        )["blocks"][0]

    @pytest.mark.parametrize("attr", ["scaled", "low_pass"])
    def test_block_bound_under_a_different_name_round_trips(
        self, decorated_blocks_module, tmp_path, attr
    ):
        cls = getattr(decorated_blocks_module, attr)
        loaded, _ = self._round_trip(cls(id="b"), tmp_path)
        assert type(loaded) is cls

    def test_block_with_declared_port_shapes_round_trips(self, decorated_blocks_module, tmp_path):
        cls = decorated_blocks_module.vec_gain
        loaded, entry = self._round_trip(cls(id="v", k=3.0), tmp_path)
        assert type(loaded) is cls
        assert loaded.port_shapes_in == ((3,),)
        assert loaded.port_shapes_out == ((3,),)
        assert loaded._params == {"k": 3.0}
        # port shape はデコレータの宣言が SSOT なので、ブロック entry には書かない
        assert "port_shapes_in" not in entry
        assert "port_shapes_out" not in entry

    def test_two_classes_with_the_same_name_are_rejected_as_ambiguous(
        self, decorated_blocks_module
    ):
        with pytest.raises(UnknownBlockTypeError, match="more than one class named 'Twin'"):
            resolve_block_class("decoblocks_probe.ambiguous.Twin")

    def test_class_imported_from_another_module_is_not_picked_up(self, decorated_blocks_module):
        """``reexport`` は ``blocks`` の ``Scaled`` を持つだけ。定義元でないモジュールの
        型名としては解決しない (型名はクラスを定義したモジュールで決まる)。"""
        with pytest.raises(UnknownBlockTypeError, match="has no attribute 'Scaled'"):
            resolve_block_class("decoblocks_probe.reexport.Scaled")
        assert (
            resolve_block_class("decoblocks_probe.blocks.Scaled") is decorated_blocks_module.scaled
        )
