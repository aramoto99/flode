"""管理ソースの読み込み・検証・再読み込み (ADR-0081 §論点 1・2・6・10、X-1、P1・P2・P6)。"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import sys
import textwrap
import threading
import types
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks.sinks import Scope
from flode.blocks.sources import Constant
from flode.core import persistence
from flode.exceptions import BlockReloadInProgressError, UnknownBlockTypeError
from flode.userblocks import LoadRequest, _loader, current_report, load_sources, reload_sources

from .conftest import WriteFile

FUNC_FORM = '''
from flode import block


@block
def moving_average(t: float, u: float, *, k: float = 2.0) -> float:
    """Scale the input.

    Args:
        t: Time.
        k: Gain applied to the input.
    """
    return k * u
'''

CLASS_FORM = """
from flode import block


@block
class accumulator:
    k: float = 1.0

    def output(self, t: float, u: float) -> float:
        return self.k * u
"""

SUBCLASS_FORM = '''
import numpy as np
from flode import Block


class Offset(Block):
    """Add a constant offset."""

    def __init__(self, c: float = 1.0, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)
        self.c = c
        self._params = {"c": c}

    def output(self, t, x, u):
        return np.array([u[0] + self.c])
'''


def _load(workspace: Path | None = None, **kwargs: object):
    return load_sources(LoadRequest(workspace=workspace, **kwargs))  # type: ignore[arg-type]


def _errors(report, severity: str = "error"):
    return [e for e in report.errors if e.severity == severity]


class TestTypeNames:
    def test_three_forms_are_loaded_with_generated_class_names(
        self, workspace: Path, write_block: WriteFile
    ):
        write_block("filters.py", FUNC_FORM)
        write_block("acc.py", CLASS_FORM)
        write_block("offset.py", SUBCLASS_FORM)

        report = _load(workspace)

        assert report.blocks == (
            "flode_ws.acc.Accumulator",
            "flode_ws.filters.MovingAverage",
            "flode_ws.offset.Offset",
        )
        assert _errors(report) == []
        table = persistence.managed_block_types()
        assert set(table) == set(report.blocks)
        assert persistence.resolve_block_class("flode_ws.filters.MovingAverage") is (
            sys.modules["flode_ws.filters"].moving_average
        )

    def test_subpackage_type_name(self, workspace: Path, write_block: WriteFile):
        write_block("control/__init__.py", "")
        write_block("control/pid.py", SUBCLASS_FORM.replace("Offset", "MyPid"))

        report = _load(workspace)

        assert report.blocks == ("flode_ws.control.pid.MyPid",)

    def test_metadata_from_docstring(self, workspace: Path, write_block: WriteFile):
        write_block("filters.py", FUNC_FORM)

        (info,) = _load(workspace).block_infos

        assert info.description == "Scale the input."
        assert [(p.name, p.default, p.description) for p in info.params] == [
            ("k", 2.0, "Gain applied to the input.")
        ]
        assert (info.n_inputs, info.n_outputs, info.source, info.path) == (
            1,
            1,
            "workspace",
            "blocks/filters.py",
        )

    def test_save_load_round_trip_after_moving_workspace(
        self, workspace: Path, write_block: WriteFile, tmp_path: Path
    ):
        write_block("filters.py", FUNC_FORM)
        _load(workspace)
        cls = persistence.resolve_block_class("flode_ws.filters.MovingAverage")
        sim = Simulator(t_end=0.03, dt=0.01)
        sim.add(Constant(value=3.0, id="src"))
        sim.add(cls(k=4.0, id="avg"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "avg")
        sim.connect("avg", "scope")
        model = tmp_path / "model.flw.json"
        sim.save(model)
        assert '"flode_ws.filters.MovingAverage"' in model.read_text(encoding="utf-8")

        _loader.unload_sources()
        moved = tmp_path / "elsewhere" / "ws2"
        moved.parent.mkdir()
        shutil.move(str(workspace), str(moved))
        _load(moved)

        loaded = Simulator.load(model)
        loaded.run()
        np.testing.assert_allclose(loaded.get_block("scope").values[:, 0], 12.0)

    def test_reserved_type_without_table_entry_is_not_imported(
        self, workspace: Path, write_block: WriteFile
    ):
        write_block("filters.py", "raise RuntimeError('must not be imported')\n")
        with pytest.raises(UnknownBlockTypeError, match="load_blocks"):
            persistence.resolve_block_class("flode_ws.filters.MovingAverage")
        assert "flode_ws.filters" not in sys.modules


class TestExclusionRules:
    def test_p1_rules(self, workspace: Path, write_block: WriteFile):
        write_block("_helper.py", "from flode import block\n" + FUNC_FORM.split("\n", 2)[2])
        write_block(
            "mixed.py",
            '''
            from flode import Block, block
            from flode.blocks.mathops import Gain


            @block
            def _private(t: float, u: float, *, k: float = 1.0) -> float:
                return u


            class AbstractBase(Block):
                block_hidden = True

                def __init__(self, k: float = 1.0, **kwargs):
                    super().__init__(n_inputs=1, n_outputs=1, **kwargs)
                    self._params = {"k": k}

                def output(self, t, x, u):
                    return u


            class Concrete(AbstractBase):
                """Derived from a hidden base."""
            ''',
        )
        write_block("uses_helper.py", "from ._helper import moving_average as public_avg\n")

        report = _load(workspace)

        assert report.blocks == ("flode_ws.mixed.Concrete",)
        assert [f.path for s in report.sources for f in s.files] == ["mixed.py", "uses_helper.py"]

    def test_builtin_class_name_is_rejected_but_subclass_alias_is_allowed(
        self, workspace: Path, write_block: WriteFile
    ):
        write_block(
            "scopes.py",
            """
            from flode.blocks.sinks import Scope as _BuiltinScope


            class Scope(_BuiltinScope):
                pass


            class MyScope(_BuiltinScope):
                pass
            """,
        )

        report = _load(workspace)

        assert report.blocks == ("flode_ws.scopes.MyScope",)
        (error,) = _errors(report)
        assert error.kind == "conflict"
        assert error.type_path == "flode_ws.scopes.Scope"
        assert "display_name='Scope'" in error.message

    def test_same_name_twice_in_module_rejects_both(self, workspace: Path, write_block: WriteFile):
        write_block(
            "dup.py",
            """
            from flode import block


            @block(name="Avg")
            def first(t: float, u: float, *, k: float = 1.0) -> float:
                return u


            @block(name="Avg")
            def second(t: float, u: float, *, k: float = 1.0) -> float:
                return u
            """,
        )

        report = _load(workspace)

        assert report.blocks == ()
        (error,) = _errors(report)
        assert (error.kind, error.type_path) == ("conflict", "flode_ws.dup.Avg")

    def test_root_init_gives_info_and_is_not_run(self, workspace: Path, write_block: WriteFile):
        write_block("__init__.py", "raise RuntimeError('no')\n")
        write_block("filters.py", FUNC_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        (info,) = _errors(report, "info")
        assert info.path == "blocks/__init__.py"
        assert report.error_count == 0


class TestDefaultValues:
    @pytest.mark.parametrize(
        ("source", "message"),
        [
            (
                """
                from flode import block

                @block
                def needs_k(t: float, u: float, *, k: float) -> float:
                    return k * u
                """,
                "has no default value",
            ),
            (
                """
                from flode import block

                @block
                def obj_default(t: float, u: float, *, k=object()) -> float:
                    return u
                """,
                "cannot be saved",
            ),
            (
                """
                import numpy as np
                from flode import Block

                class WantsArray(Block):
                    def __init__(self, a=np.array([1.0, 2.0]), **kwargs):
                        if not isinstance(a, np.ndarray):
                            raise TypeError("a must be an ndarray")
                        super().__init__(n_inputs=1, n_outputs=1, **kwargs)
                        self._params = {"a": a}

                    def output(self, t, x, u):
                        return u
                """,
                "round trip",
            ),
        ],
        ids=["missing", "unserializable", "round-trip"],
    )
    def test_rejected(self, workspace: Path, write_block: WriteFile, source: str, message: str):
        write_block("bad.py", source)
        write_block("filters.py", FUNC_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        (error,) = _errors(report)
        assert error.kind == "spec"
        assert error.path == "blocks/bad.py"
        assert message in error.message
        assert error.line is not None

    def test_defaults_are_json_values(self, workspace: Path, write_block: WriteFile):
        write_block(
            "tup.py",
            """
            from flode import Block

            class Taps(Block):
                def __init__(self, taps=(1.0, 2.0), **kwargs):
                    super().__init__(n_inputs=1, n_outputs=1, **kwargs)
                    self._params = {"taps": list(taps)}

                def output(self, t, x, u):
                    return u
            """,
        )
        (info,) = _load(workspace).block_infos
        assert info.params[0].default == [1.0, 2.0]


class TestIsolation:
    @pytest.mark.parametrize(
        ("source", "kind", "line", "message"),
        [
            ("X = 1\ndef broken(:\n", "syntax", 2, "SyntaxError"),
            ("X = 1\nraise ValueError('bad import')\n", "import", 2, "ValueError: bad import"),
            ("import sys\nsys.exit(3)\n", "import", 2, "SystemExit(3)"),
            ("import not_a_real_module_xyz\n", "import", 1, "ModuleNotFoundError"),
        ],
        ids=["syntax", "exception", "system-exit", "missing-dependency"],
    )
    def test_file_failure_is_isolated(
        self, workspace: Path, write_block: WriteFile, source, kind, line, message
    ):
        write_block("broken.py", source)
        write_block("filters.py", FUNC_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        (error,) = _errors(report)
        assert (error.kind, error.path, error.line) == (kind, "blocks/broken.py", line)
        assert message in error.message
        (source_info,) = report.sources
        assert {f.path: f.status for f in source_info.files} == {
            "broken.py": "error",
            "filters.py": "ok",
        }

    def test_dependency_failure_reports_both_files(self, workspace: Path, write_block: WriteFile):
        write_block("common.py", "X = 1\nraise RuntimeError('common failed')\n")
        write_block("filters.py", "from . import common\n" + FUNC_FORM)

        report = _load(workspace)

        paths = {e.path: e for e in _errors(report)}
        assert set(paths) == {"blocks/common.py", "blocks/filters.py"}
        assert paths["blocks/filters.py"].line == 1
        assert "common.py, line 2" in paths["blocks/filters.py"].message

    def test_keyboard_interrupt_propagates(self, workspace: Path, write_block: WriteFile):
        write_block("stop.py", "raise KeyboardInterrupt\n")
        with pytest.raises(KeyboardInterrupt):
            _load(workspace)

    def test_long_message_is_truncated(self, workspace: Path, write_block: WriteFile):
        write_block("long.py", f"raise ValueError({'x' * 5000!r})\n")
        (error,) = _errors(_load(workspace))
        assert len(error.message) == _loader.MAX_MESSAGE_CHARS

    def test_slow_import_logs_warning(
        self, workspace: Path, write_block: WriteFile, mocker, caplog: pytest.LogCaptureFixture
    ):
        mocker.patch.object(_loader, "IMPORT_WARN_SECONDS", 0.01)
        write_block("slow.py", "import time\ntime.sleep(0.3)\n")
        with caplog.at_level(logging.WARNING, logger="flode.userblocks"):
            _load(workspace)
        assert any("blocks/slow.py" in r.getMessage() for r in caplog.records)

    def test_fast_import_does_not_warn(
        self, workspace: Path, write_block: WriteFile, caplog: pytest.LogCaptureFixture
    ):
        write_block("filters.py", FUNC_FORM)
        with caplog.at_level(logging.WARNING, logger="flode.userblocks"):
            _load(workspace)
        assert not [r for r in caplog.records if "taken more than" in r.getMessage()]


class TestReservedNameConflict:
    def test_existing_flode_ws_package_blocks_workspace(
        self, workspace: Path, write_block: WriteFile, monkeypatch: pytest.MonkeyPatch
    ):
        write_block("filters.py", FUNC_FORM)
        monkeypatch.setitem(sys.modules, "flode_ws", types.ModuleType("flode_ws"))

        report = _load(workspace)

        assert report.blocks == ()
        (error,) = _errors(report)
        assert (error.kind, error.source) == ("conflict", "workspace")
        assert "flode_ws.filters" not in sys.modules

    def test_package_on_sys_path_blocks_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        site = tmp_path / "site"
        (site / "flode_dirs").mkdir(parents=True)
        (site / "flode_dirs" / "__init__.py").write_text("", encoding="utf-8")
        monkeypatch.syspath_prepend(str(site))
        lab = tmp_path / "lab"
        lab.mkdir()
        (lab / "io.py").write_text(FUNC_FORM, encoding="utf-8")

        report = _load(dirs=(("lab", lab),))

        assert report.blocks == ()
        assert [(e.kind, e.source) for e in _errors(report)] == [("conflict", "dir:lab")]


class TestSources:
    def test_dirs_and_modules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lab = tmp_path / "lab"
        lab.mkdir()
        (lab / "io.py").write_text(FUNC_FORM, encoding="utf-8")
        site = tmp_path / "site"
        (site / "ubpkg_probe").mkdir(parents=True)
        (site / "ubpkg_probe" / "__init__.py").write_text("", encoding="utf-8")
        (site / "ubpkg_probe" / "blocks.py").write_text(SUBCLASS_FORM, encoding="utf-8")
        monkeypatch.syspath_prepend(str(site))

        report = _load(
            dirs=(("lab", lab), ("gone", tmp_path / "missing")),
            modules=("ubpkg_probe.blocks", "ubpkg_probe.blocks", "flode.blocks", "flode_ws.x"),
        )

        assert report.blocks == ("flode_dirs.lab.io.MovingAverage", "ubpkg_probe.blocks.Offset")
        assert [s.id for s in report.sources] == [
            "dir:lab",
            "module:ubpkg_probe.blocks",
            "module:flode.blocks",
            "module:flode_ws.x",
        ]
        assert report.restart_required_sources == (
            "module:ubpkg_probe.blocks",
            "module:flode.blocks",
            "module:flode_ws.x",
        )
        assert sorted((e.kind, e.source) for e in _errors(report)) == [
            ("config", "dir:gone"),
            ("config", "module:flode.blocks"),
            ("config", "module:flode_ws.x"),
        ]
        # modules のクラスも表で解決でき、allowlist には登録しない
        assert persistence.resolve_block_class("ubpkg_probe.blocks.Offset").__name__ == "Offset"
        assert "ubpkg_probe." not in persistence._extra_allowed_prefixes

    def test_missing_blocks_folder_is_silent(self, tmp_path: Path):
        ws = tmp_path / "plain"
        ws.mkdir()
        report = _load(ws)
        assert (report.blocks, report.errors, report.sources) == ((), (), ())

    def test_missing_workspace_is_config_error(self, tmp_path: Path):
        report = _load(tmp_path / "nope")
        assert [e.kind for e in _errors(report)] == ["config"]


class TestCwdWorkspace:
    def test_home_is_skipped_only_when_from_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        fake_home = tmp_path / "home"
        (fake_home / "blocks").mkdir(parents=True)
        (fake_home / "blocks" / "filters.py").write_text(FUNC_FORM, encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        skipped = load_sources(LoadRequest(workspace=fake_home, workspace_from_cwd=True))
        assert skipped.blocks == ()
        (info,) = _errors(skipped, "info")
        assert info.kind == "config"

        explicit = load_sources(LoadRequest(workspace=fake_home, workspace_from_cwd=False))
        assert explicit.blocks == ("flode_ws.filters.MovingAverage",)

    def test_filesystem_root_detection(self):
        anchor = Path(os.path.abspath(os.sep))
        assert _loader._is_home_or_filesystem_root(anchor)

    def test_other_cwd_is_read_and_marked(
        self, workspace: Path, write_block: WriteFile, caplog: pytest.LogCaptureFixture
    ):
        write_block("filters.py", FUNC_FORM)
        with caplog.at_level(logging.INFO, logger="flode.userblocks"):
            report = load_sources(LoadRequest(workspace=workspace, workspace_from_cwd=True))
        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        assert report.sources[0].from_cwd is True
        assert any("current directory" in r.getMessage() for r in caplog.records)


class TestReload:
    def test_reload_reflects_edit_add_and_delete(self, workspace: Path, write_block: WriteFile):
        filters = write_block("filters.py", FUNC_FORM)
        write_block("acc.py", CLASS_FORM)
        first = _load(workspace)
        old_cls = persistence.resolve_block_class("flode_ws.filters.MovingAverage")
        assert first.added == first.blocks

        filters.write_text(FUNC_FORM.replace("k: float = 2.0", "k: float = 5.0"), encoding="utf-8")
        (workspace / "blocks" / "acc.py").unlink()
        write_block("offset.py", SUBCLASS_FORM)
        second = reload_sources()

        assert second.added == ("flode_ws.offset.Offset",)
        assert second.removed == ("flode_ws.acc.Accumulator",)
        assert second.changed == ("flode_ws.filters.MovingAverage",)
        new_cls = persistence.resolve_block_class("flode_ws.filters.MovingAverage")
        assert new_cls is not old_cls
        assert old_cls(id="a")._params == {"k": 2.0}  # 旧クラスは旧定義のまま
        assert new_cls(id="b")._params == {"k": 5.0}
        with pytest.raises(UnknownBlockTypeError):
            persistence.resolve_block_class("flode_ws.acc.Accumulator")
        assert current_report() is second

    def test_same_second_same_size_edit_is_picked_up(self, workspace: Path, write_block: WriteFile):
        path = write_block("filters.py", FUNC_FORM)
        _load(workspace)
        stat = path.stat()
        path.write_text(FUNC_FORM.replace("2.0", "7.0"), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert path.stat().st_size == stat.st_size

        report = reload_sources()

        assert report.changed == ("flode_ws.filters.MovingAverage",)
        (info,) = report.block_infos
        assert info.params[0].default == 7.0

    def test_unchanged_reload_has_empty_diff(self, workspace: Path, write_block: WriteFile):
        write_block("filters.py", FUNC_FORM)
        _load(workspace)
        report = reload_sources()
        assert (report.added, report.removed, report.changed) == ((), (), ())

    def test_broken_file_drops_its_blocks(self, workspace: Path, write_block: WriteFile):
        path = write_block("filters.py", FUNC_FORM)
        _load(workspace)
        path.write_text("def broken(:\n", encoding="utf-8")
        report = reload_sources()
        assert report.removed == ("flode_ws.filters.MovingAverage",)
        assert persistence.managed_block_types() == {}

    def test_modules_are_not_reimported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        site = tmp_path / "site"
        site.mkdir()
        module_file = site / "ubmod_probe.py"
        module_file.write_text(SUBCLASS_FORM, encoding="utf-8")
        monkeypatch.syspath_prepend(str(site))
        _load(modules=("ubmod_probe",))
        cls = persistence.resolve_block_class("ubmod_probe.Offset")

        module_file.write_text(SUBCLASS_FORM.replace("c: float = 1.0", "c: float = 9.0"), "utf-8")
        report = reload_sources()

        assert persistence.resolve_block_class("ubmod_probe.Offset") is cls
        assert report.changed == ()
        assert report.restart_required_sources == ("module:ubmod_probe",)
        assert "ubmod_probe" in sys.modules

    def test_second_load_switches_workspace(self, tmp_path: Path):
        ws_a = tmp_path / "a"
        ws_b = tmp_path / "b"
        for ws, body in ((ws_a, FUNC_FORM), (ws_b, SUBCLASS_FORM)):
            (ws / "blocks").mkdir(parents=True)
            (ws / "blocks" / "mod.py").write_text(body, encoding="utf-8")

        _load(ws_a)
        report = _load(ws_b)

        assert report.blocks == ("flode_ws.mod.Offset",)
        assert report.removed == ("flode_ws.mod.MovingAverage",)
        assert Path(sys.modules["flode_ws.mod"].__file__).parent.parent == ws_b.resolve()

    def test_unload_restores_table_and_sys_modules(self, workspace: Path, write_block: WriteFile):
        write_block("filters.py", FUNC_FORM)
        _load(workspace)
        assert "flode_ws.filters" in sys.modules

        _loader.unload_sources()

        assert persistence.managed_block_types() == {}
        assert not [m for m in sys.modules if m.split(".")[0] in ("flode_ws", "flode_dirs")]
        assert not [f for f in sys.meta_path if type(f).__name__ == "ReservedRootFinder"]
        assert current_report() is None
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.filters")


@pytest.fixture
def gate() -> Iterator[threading.Event]:
    """ユーザーコードの import を止めておくための Event (テスト専用の一時モジュール経由)。"""
    event = threading.Event()
    module = types.ModuleType("_flode_userblocks_test_gate")
    module.started = threading.Event()  # type: ignore[attr-defined]
    module.release = event  # type: ignore[attr-defined]
    sys.modules[module.__name__] = module
    yield event
    event.set()
    sys.modules.pop(module.__name__, None)


class TestConcurrency:
    def test_second_request_while_loading_is_rejected(
        self, workspace: Path, write_block: WriteFile, gate: threading.Event
    ):
        write_block(
            "slow.py",
            textwrap.dedent(
                """
                import _flode_userblocks_test_gate as gate
                gate.started.set()
                gate.release.wait(10)
                """
            ),
        )
        results: list[object] = []
        worker = threading.Thread(target=lambda: results.append(_load(workspace)))
        worker.start()
        try:
            assert sys.modules["_flode_userblocks_test_gate"].started.wait(10)
            with pytest.raises(BlockReloadInProgressError):
                reload_sources()
            with pytest.raises(BlockReloadInProgressError):
                _loader.unload_sources()
        finally:
            gate.set()
            worker.join(10)
        assert len(results) == 1


SELF_REFERENCE_DEFAULT = """
from flode import Block

_SELF = []
_SELF.append(_SELF)


class SelfRef(Block):
    def __init__(self, x=_SELF, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    def output(self, t, x, u):
        return u
"""

DEEP_DEFAULT = """
from flode import Block

_DEEP = []
_cur = _DEEP
for _ in range(100_000):
    _nxt = []
    _cur.append(_nxt)
    _cur = _nxt


class Deep(Block):
    def __init__(self, x=_DEEP, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    def output(self, t, x, u):
        return u
"""

BAD_FLOAT_DEFAULT = """
from flode import Block


class BadFloat(float):
    def __float__(self):
        raise RuntimeError("no float for you")


class UsesBadFloat(Block):
    def __init__(self, x=BadFloat(1.0), **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    def output(self, t, x, u):
        return u
"""

UNPRINTABLE_IMPORT_ERROR = """
class Unprintable(Exception):
    def __str__(self):
        raise RuntimeError("cannot print me")


raise Unprintable()
"""

CANCELLED_AT_IMPORT = """
import asyncio

raise asyncio.CancelledError()
"""

METACLASS_PROPERTY = """
from flode import Block


class Meta(type(Block)):
    @property
    def block_category(cls):
        raise RuntimeError("metaclass property failed")


class MetaBlock(Block, metaclass=Meta):
    def __init__(self, k: float = 1.0, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    def output(self, t, x, u):
        return u
"""

OWN_DISPLAY_NAME_PROPERTY = """
from flode import Block


class PropBlock(Block):
    @property
    def block_display_name(self):
        raise RuntimeError("never read")

    def __init__(self, k: float = 1.0, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    def output(self, t, x, u):
        return u
"""

SNEAKY_CLASS_ATTRIBUTE = """
class Sneaky:
    @property
    def __class__(self):
        raise RuntimeError("sneaky __class__")


sneaky = Sneaky()
"""


class TestUserCodeBoundary:
    """想定外の例外でも、そのファイル / ブロックだけが失敗し他は読み込まれる (MUST)。"""

    @pytest.mark.parametrize(
        ("source", "must_fail"),
        [
            (SELF_REFERENCE_DEFAULT, True),
            (DEEP_DEFAULT, True),
            (BAD_FLOAT_DEFAULT, True),
            (UNPRINTABLE_IMPORT_ERROR, True),
            (CANCELLED_AT_IMPORT, True),
            (METACLASS_PROPERTY, True),
            (OWN_DISPLAY_NAME_PROPERTY, True),
            (SNEAKY_CLASS_ATTRIBUTE, False),
        ],
        ids=[
            "self-reference",
            "deep-nesting",
            "float-dunder",
            "unprintable-exception",
            "cancelled-error",
            "metaclass-property",
            "own-property",
            "sneaky-class-attr",
        ],
    )
    def test_good_blocks_still_load(
        self, workspace: Path, write_block: WriteFile, source: str, must_fail: bool
    ):
        import flode

        write_block("bad.py", source)
        write_block("filters.py", FUNC_FORM)

        report = flode.load_blocks(workspace, strict=False)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        assert persistence.resolve_block_class("flode_ws.filters.MovingAverage")
        errors = _errors(report)
        assert all(e.path == "blocks/bad.py" for e in errors)
        assert all(len(e.message) <= _loader.MAX_MESSAGE_CHARS for e in errors)
        if must_fail:
            assert errors
        assert not _loader._RELOAD_LOCK.locked()

    def test_unprintable_exception_message(self, workspace: Path, write_block: WriteFile):
        write_block("bad.py", UNPRINTABLE_IMPORT_ERROR)
        (error,) = _errors(_load(workspace))
        assert error.message.startswith("Unprintable: <unprintable>")

    def test_generator_exit_propagates(self, workspace: Path, write_block: WriteFile):
        write_block("stop.py", "raise GeneratorExit\n")
        with pytest.raises(GeneratorExit):
            _load(workspace)

    def test_keyboard_interrupt_keeps_previous_state(self, workspace: Path, write_block: WriteFile):
        write_block("filters.py", FUNC_FORM)
        _load(workspace)
        table = dict(persistence.managed_block_types())
        module = sys.modules["flode_ws.filters"]
        assert _loader._finder is not None
        roots = _loader._finder.roots
        stop = write_block("stop.py", "raise KeyboardInterrupt\n")

        with pytest.raises(KeyboardInterrupt):
            reload_sources()

        assert dict(persistence.managed_block_types()) == table
        assert not _loader._RELOAD_LOCK.locked()
        assert sys.modules["flode_ws.filters"] is module
        assert "flode_ws.stop" not in sys.modules
        assert _loader._finder.roots is roots
        type_path = "flode_ws.filters.MovingAverage"
        assert persistence.resolve_block_class(type_path) is table[type_path]
        report = current_report()
        assert report is not None and type_path in report.blocks
        stop.unlink()
        assert reload_sources().blocks == (type_path,)

    def test_commit_failure_rolls_back(self, workspace: Path, write_block: WriteFile, mocker):
        write_block("filters.py", FUNC_FORM)
        _load(workspace)
        module = sys.modules["flode_ws.filters"]
        mocker.patch.object(
            _loader, "_replace_managed_block_types", side_effect=RuntimeError("commit failed")
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            reload_sources()
        assert sys.modules["flode_ws.filters"] is module


class TestHijackProtection:
    def test_rewriting_module_and_name_is_rejected(self, workspace: Path, write_block: WriteFile):
        from flode.blocks.mathops import Gain

        write_block(
            "hijack.py",
            """
            from flode import Block


            class Hijack(Block):
                def __init__(self, k: float = 1.0, **kwargs):
                    super().__init__(n_inputs=1, n_outputs=1, **kwargs)
                    type(self).__module__ = "flode.blocks.mathops"
                    type(self).__name__ = "Gain"

                def output(self, t, x, u):
                    return u
            """,
        )
        write_block("filters.py", FUNC_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        (error,) = _errors(report)
        assert error.type_path == "flode_ws.hijack.Hijack"
        assert "changed its module or name" in error.message
        assert persistence.resolve_block_class("flode.blocks.mathops.Gain") is Gain
        assert "flode.blocks.mathops.Gain" not in persistence.managed_block_types()


class _RaisingFinder:
    def find_spec(self, name, path=None, target=None):
        raise RuntimeError("broken third-party finder")


class TestFailClosed:
    def test_finder_error_counts_as_conflict(
        self, workspace: Path, write_block: WriteFile, caplog: pytest.LogCaptureFixture
    ):
        write_block("filters.py", FUNC_FORM)
        sys.meta_path.append(_RaisingFinder())  # conftest が meta_path を戻す

        with caplog.at_level(logging.WARNING, logger="flode.userblocks"):
            report = _load(workspace)

        assert report.blocks == ()
        assert [(e.kind, e.source) for e in _errors(report)] == [("conflict", "workspace")]
        assert any("broken third-party finder" in r.getMessage() for r in caplog.records)

    def test_unknown_home_skips_cwd_workspace(
        self, workspace: Path, write_block: WriteFile, monkeypatch: pytest.MonkeyPatch
    ):
        write_block("filters.py", FUNC_FORM)

        def _no_home(cls):
            raise RuntimeError("no home")

        monkeypatch.setattr(Path, "home", classmethod(_no_home))

        skipped = load_sources(LoadRequest(workspace=workspace, workspace_from_cwd=True))
        assert skipped.blocks == ()
        assert [e.kind for e in _errors(skipped, "info")] == ["config"]
        explicit = load_sources(LoadRequest(workspace=workspace))
        assert explicit.blocks == ("flode_ws.filters.MovingAverage",)


def _make_dir_link(link: Path, target: Path) -> None:
    """ディレクトリへのリンクを作る (symlink、Windows で不可なら junction、どちらも不可なら skip)。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
    pytest.skip("cannot create a directory link in this environment")


class TestLinks:
    def test_directory_link_outside_root_is_not_read(
        self, workspace: Path, write_block: WriteFile, tmp_path: Path
    ):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "__init__.py").write_text("raise RuntimeError('outside init ran')\n", "utf-8")
        (outside / "evil.py").write_text("raise RuntimeError('outside ran')\n", "utf-8")
        _make_dir_link(workspace / "blocks" / "ext", outside)
        write_block("filters.py", FUNC_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.filters.MovingAverage",)
        assert report.error_count == 0
        (info,) = _errors(report, "info")
        assert info.path == "blocks/ext"
        assert "outside" in info.message
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.ext")

    def test_file_link_outside_root_is_not_read(
        self, workspace: Path, write_block: WriteFile, tmp_path: Path
    ):
        outside = tmp_path / "outside.py"
        outside.write_text("raise RuntimeError('outside ran')\n", encoding="utf-8")
        try:
            os.symlink(outside, workspace / "blocks" / "evil.py")
        except (OSError, NotImplementedError):
            pytest.skip("cannot create a file symlink in this environment")

        report = _load(workspace)

        assert report.error_count == 0
        assert [e.path for e in _errors(report, "info")] == ["blocks/evil.py"]
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.evil")

    def test_link_inside_root_is_read(self, workspace: Path, write_block: WriteFile):
        write_block("realpkg/__init__.py", "")
        write_block("realpkg/mod.py", SUBCLASS_FORM)
        _make_dir_link(workspace / "blocks" / "alias", workspace / "blocks" / "realpkg")

        report = _load(workspace)

        assert report.blocks == ("flode_ws.alias.mod.Offset", "flode_ws.realpkg.mod.Offset")


class TestMoreSourceRules:
    def test_module_file_shadowed_by_package_gives_info(
        self, workspace: Path, write_block: WriteFile
    ):
        write_block("pkg.py", "raise RuntimeError('shadowed file must not run')\n")
        write_block("pkg/__init__.py", "")
        write_block("pkg/mod.py", SUBCLASS_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.pkg.mod.Offset",)
        assert report.error_count == 0
        assert [e.path for e in _errors(report, "info")] == ["blocks/pkg.py"]

    def test_subfolder_without_init_with_sources_gives_info(
        self, workspace: Path, write_block: WriteFile
    ):
        """``__init__.py`` の無いサブフォルダは読まないが、.py があれば理由を告知する。

        回帰: 告知が無く、サブフォルダに置いたブロックが黙ってパレットに出なかった。
        """
        write_block("io/logger.py", "raise RuntimeError('must not run')\n")
        write_block("data/readme.txt", "not python\n")  # .py が無いフォルダは告知しない
        write_block("top.py", SUBCLASS_FORM)

        report = _load(workspace)

        assert report.blocks == ("flode_ws.top.Offset",)
        assert report.error_count == 0
        infos = _errors(report, "info")
        assert [e.path for e in infos] == ["blocks/io/"]
        assert "__init__.py" in infos[0].message

    @pytest.mark.parametrize(
        "rel",
        [
            pytest.param("helpers/_private.py", id="only-underscore-sources"),
            pytest.param("my-dir/mod.py", id="invalid-folder-name"),
        ],
    )
    def test_subfolder_without_init_notice_is_not_given_when_init_would_not_help(
        self, workspace: Path, write_block: WriteFile, rel: str
    ):
        write_block(rel, "raise RuntimeError('must not run')\n")

        report = _load(workspace)

        assert [e.path for e in _errors(report, "info") if "__init__.py" in e.message] == []

    def test_nan_default_is_not_reported_as_changed(self, workspace: Path, write_block: WriteFile):
        write_block("nan.py", SUBCLASS_FORM.replace("c: float = 1.0", "c: float = float('nan')"))
        _load(workspace)
        assert reload_sources().changed == ()


class TestPrivateDependencies:
    """userblocks が依存する他モジュールの private 名 (リネーム検知用)。"""

    @pytest.mark.parametrize(
        "name",
        [
            "_CLASSIFICATION",
            "_CONTROL_PORT_INDEX",
            "_SHAPE_RULES",
            "_SHAPE_SOURCES",
            "_STATE_VIA_FLOAT64",
        ],
    )
    def test_signals_tables(self, name: str):
        from flode.core import signals

        assert hasattr(signals, name)

    def test_decorator_generated_attributes(self):
        from flode import block

        @block
        def probe_fn(t: float, u: float, *, k: float = 1.0) -> float:
            return u

        @block
        class probe_cls:
            k: float = 1.0

            def output(self, t: float, u: float) -> float:
                return u

        for cls in (probe_fn, probe_cls):
            assert "_flode_params_spec" in vars(cls)
            assert "_flode_structure" in vars(cls)
        assert "_flode_func" in vars(probe_fn)
        assert "_flode_user_cls" in vars(probe_cls)
