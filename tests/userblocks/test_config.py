"""読み込み元指定の検証と config ``[blocks]`` 節 (SPEC-0033 P3)。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from flode.exceptions import BlockSourceConfigError
from flode.userblocks import parse_blocks_config, read_blocks_config
from flode.userblocks._config import build_request


class TestParseBlocksConfig:
    def test_valid_section(self, tmp_path: Path):
        cfg = parse_blocks_config(
            {
                "dirs": {"lab": "lab-blocks"},
                "modules": ["mypkg.blocks"],
                "allow_non_loopback": True,
            },
            base_dir=tmp_path,
        )
        assert cfg.dirs == (("lab", (tmp_path / "lab-blocks").resolve()),)
        assert cfg.modules == ("mypkg.blocks",)
        assert cfg.allow_non_loopback is True

    def test_home_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        cfg = parse_blocks_config({"dirs": {"lab": "~/lab"}}, base_dir=tmp_path)
        assert cfg.dirs == (("lab", (tmp_path / "home" / "lab").resolve()),)

    def test_none_is_empty(self, tmp_path: Path):
        cfg = parse_blocks_config(None, base_dir=tmp_path)
        assert (cfg.dirs, cfg.modules, cfg.allow_non_loopback) == ((), (), False)

    @pytest.mark.parametrize(
        "section",
        [
            [],
            {"dirs": ["lab"]},
            {"dirs": {"1lab": "x"}},
            {"dirs": {"class": "x"}},
            {"dirs": {"_lab": "x"}},
            {"dirs": {"lab": 3}},
            {"modules": "mypkg"},
            {"modules": [1]},
            {"allow_non_loopback": "yes"},
        ],
    )
    def test_type_violations(self, tmp_path: Path, section):
        with pytest.raises(BlockSourceConfigError):
            parse_blocks_config(section, base_dir=tmp_path)

    def test_unknown_key_warns(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="flode.userblocks"):
            parse_blocks_config({"plugins": []}, base_dir=tmp_path)
        assert any("plugins" in r.getMessage() for r in caplog.records)


class TestReadBlocksConfig:
    def test_missing_file_is_empty(self, tmp_path: Path):
        assert read_blocks_config(tmp_path / "none.toml").modules == ()

    def test_reads_blocks_section_relative_to_file(self, tmp_path: Path):
        path = tmp_path / "conf" / "config.toml"
        path.parent.mkdir()
        path.write_text('[blocks]\ndirs = { lab = "lab" }\nmodules = ["m"]\n', encoding="utf-8")
        cfg = read_blocks_config(path)
        assert cfg.dirs == (("lab", (tmp_path / "conf" / "lab").resolve()),)
        assert cfg.modules == ("m",)

    def test_broken_toml(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("[blocks\n", encoding="utf-8")
        with pytest.raises(BlockSourceConfigError):
            read_blocks_config(path)


class TestBuildRequest:
    def test_config_is_appended_and_duplicates_rejected(self, tmp_path: Path):
        cfg = parse_blocks_config({"dirs": {"lab": str(tmp_path)}}, base_dir=tmp_path)
        with pytest.raises(BlockSourceConfigError, match="duplicated"):
            build_request(None, dirs={"lab": tmp_path}, modules=None, config=cfg)

    def test_workspace_type(self):
        with pytest.raises(BlockSourceConfigError):
            build_request(3, dirs=None, modules=None)  # type: ignore[arg-type]


def test_non_utf8_config_is_a_config_error(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff\xfe[blocks]\n")
    with pytest.raises(BlockSourceConfigError):
        read_blocks_config(path)
