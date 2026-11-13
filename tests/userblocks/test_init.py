"""Python API ``flode.load_blocks`` / ``flode.unload_blocks`` (ADR-0081 §論点 9) と U1 との結合。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import flode
from flode.core import persistence

from .conftest import WriteFile

GOOD = """
from flode import block


@block
def doubler_probe(t: float, u: float, *, k: float = 2.0) -> float:
    return k * u
"""


class TestLoadBlocks:
    def test_loads_and_unloads(self, workspace: Path, write_block: WriteFile):
        write_block("good.py", GOOD)

        report = flode.load_blocks(workspace)

        assert report.blocks == ("flode_ws.good.DoublerProbe",)
        flode.unload_blocks()
        assert dict(persistence.managed_block_types()) == {}
        assert "flode_ws" not in sys.modules

    def test_strict_raises_after_loading_everything(self, workspace: Path, write_block: WriteFile):
        write_block("good.py", GOOD)
        write_block("bad.py", "raise ValueError('nope')\n")

        with pytest.raises(flode.BlockLoadError, match="nope") as info:
            flode.load_blocks(workspace)

        assert info.value.report.blocks == ("flode_ws.good.DoublerProbe",)
        assert "flode_ws.good.DoublerProbe" in persistence.managed_block_types()

    def test_non_strict_returns_report(self, workspace: Path, write_block: WriteFile):
        write_block("bad.py", "raise ValueError('nope')\n")
        report = flode.load_blocks(workspace, strict=False)
        assert report.error_count == 1

    def test_info_entries_do_not_trigger_strict(self, workspace: Path, write_block: WriteFile):
        write_block("__init__.py", "")
        write_block("good.py", GOOD)
        assert flode.load_blocks(workspace).error_count == 0

    def test_none_workspace_reads_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / "blocks").mkdir()
        (tmp_path / "blocks" / "good.py").write_text(GOOD, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert flode.load_blocks().blocks == ()

    def test_dirs_relative_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / "lab").mkdir()
        (tmp_path / "lab" / "io.py").write_text(GOOD, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        report = flode.load_blocks(dirs={"lab": "lab"})
        assert report.blocks == ("flode_dirs.lab.io.DoublerProbe",)

    def test_use_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        home = tmp_path / "home"
        (home / ".flode").mkdir(parents=True)
        (home / "lab").mkdir()
        (home / "lab" / "io.py").write_text(GOOD, encoding="utf-8")
        (home / ".flode" / "config.toml").write_text(
            '[blocks]\ndirs = { lab = "~/lab" }\n', encoding="utf-8"
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        assert flode.load_blocks().blocks == ()
        assert flode.load_blocks(use_config=True).blocks == ("flode_dirs.lab.io.DoublerProbe",)

    def test_invalid_dir_name(self):
        with pytest.raises(flode.BlockSourceConfigError):
            flode.load_blocks(dirs={"not-valid": "."})


class TestDecoratorMetadataIntegration:
    """U1 の ``@block`` メタデータ引数・sink が読み込みに反映される。"""

    def test_decorator_metadata_and_sink(self, workspace: Path, write_block: WriteFile):
        write_block(
            "meta.py",
            '''
            from flode import block


            @block(
                category="Filters",
                display_name={"ja": "整形", "en": "Shaper"},
                choices={"mode": ("fast", "slow")},
                param_descriptions={"k": "Explicit gain"},
                input_names=("in",),
            )
            def shaper_probe(t: float, u: float, *, mode: str = "fast", k: float = 1.0) -> float:
                """Shape the input.

                Args:
                    k: Docstring gain.
                    mode: Docstring mode.
                """
                return k * u


            @block(outputs=0)
            def logger_probe(t: float, u: float, *, path: str = "out.csv") -> None:
                """Write the input."""
            ''',
        )

        report = flode.load_blocks(workspace)

        infos = {i.class_name: i for i in report.block_infos}
        shaper = infos["ShaperProbe"]
        assert shaper.category == "Filters"
        assert (shaper.display_name, dict(shaper.display_name_i18n)) == (
            "Shaper",
            {"ja": "整形", "en": "Shaper"},
        )
        assert shaper.description == "Shape the input."
        assert {p.name: (p.description, p.choices) for p in shaper.params} == {
            "mode": ("Docstring mode.", ("fast", "slow")),
            "k": ("Explicit gain", None),
        }
        assert shaper.input_names == ("in",)
        sink = infos["LoggerProbe"]
        assert (sink.n_inputs, sink.n_outputs) == (1, 0)

    def test_decorator_choice_default_mismatch_is_a_block_error(
        self, workspace: Path, write_block: WriteFile
    ):
        write_block(
            "bad.py",
            """
            from flode import block


            @block(choices={"mode": ("a", "b")})
            def mismatch_probe(t: float, u: float, *, mode: str = "z") -> float:
                return u
            """,
        )
        report = flode.load_blocks(workspace, strict=False)
        assert report.blocks == ()
        assert report.error_count == 1
