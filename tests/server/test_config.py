"""``pyflw.server.config`` のユニットテスト (SPEC-0004)。

Jupyter Lab 準拠の挙動 (= 不在は default で黙起動、不正値は厳格エラー、未知キーは
warning + 継続) を確認する。``~/.pyflw/config.toml`` の探索パスは ``Path.home()`` を
monkeypatch して隔離する。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pyflw.exceptions import PyflwError
from pyflw.server.config import (
    SettingsResolver,
    generate_config_template,
    load_config_file,
    resolve_config_path,
)
from pyflw.server.settings import Settings

# ---------------------------------------------------------------------------
# load_config_file
# ---------------------------------------------------------------------------


class TestLoadConfigFile:
    def test_parses_full_schema(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[server]\n'
            'host = "0.0.0.0"\n'
            "port = 9000\n"
            "\n"
            "[settings]\n"
            'workspace = "~/projA"\n'
            "scope_batch_size = 200\n"
            "max_concurrent = 8\n"
            'allow_origins = ["http://localhost:5173"]\n'
            'library_paths = ["./libs"]\n'
            "bundle_builtin_libraries = false\n",
            encoding="utf-8",
        )
        cfg = load_config_file(cfg_path)
        assert cfg["server"]["host"] == "0.0.0.0"
        assert cfg["server"]["port"] == 9000
        assert cfg["settings"]["workspace"] == "~/projA"
        assert cfg["settings"]["scope_batch_size"] == 200
        assert cfg["settings"]["max_concurrent"] == 8
        assert cfg["settings"]["allow_origins"] == ["http://localhost:5173"]
        assert cfg["settings"]["library_paths"] == ["./libs"]
        assert cfg["settings"]["bundle_builtin_libraries"] is False

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config_file(cfg_path)
        assert cfg == {}

    def test_toml_syntax_error_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("[server\nport = 8770\n", encoding="utf-8")
        with pytest.raises(PyflwError, match="Failed to parse config"):
            load_config_file(cfg_path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "does-not-exist.toml"
        with pytest.raises(PyflwError, match="does not exist"):
            load_config_file(cfg_path)

    def test_directory_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PyflwError, match="not a file|directory"):
            load_config_file(tmp_path)


# ---------------------------------------------------------------------------
# resolve_config_path
# ---------------------------------------------------------------------------


class TestResolveConfigPath:
    def test_explicit_existing_file_returned(self, tmp_path: Path) -> None:
        cfg = tmp_path / "my.toml"
        cfg.write_text("", encoding="utf-8")
        result = resolve_config_path(explicit=cfg)
        assert result == cfg.resolve()

    def test_explicit_missing_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "missing.toml"
        with pytest.raises(PyflwError, match="does not exist"):
            resolve_config_path(explicit=cfg)

    def test_explicit_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PyflwError, match="not a file|directory"):
            resolve_config_path(explicit=tmp_path)

    def test_default_search_finds_user_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".pyflw").mkdir(parents=True)
        cfg = home / ".pyflw" / "config.toml"
        cfg.write_text("", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        result = resolve_config_path(explicit=None)
        assert result == cfg

    def test_default_search_no_file_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        assert resolve_config_path(explicit=None) is None


# ---------------------------------------------------------------------------
# SettingsResolver
# ---------------------------------------------------------------------------


class TestSettingsResolver:
    def test_cli_overrides_file(self, tmp_path: Path) -> None:
        ws_cli = tmp_path / "cli_ws"
        ws_file = tmp_path / "file_ws"
        ws_cli.mkdir()
        ws_file.mkdir()
        resolver = SettingsResolver(
            cli={"workspace": ws_cli, "port": 9000},
            file_config={
                "server": {"port": 8000, "host": "0.0.0.0"},
                "settings": {"workspace": str(ws_file)},
            },
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == ws_cli.resolve()
        host, port = resolver.build_server_bind()
        assert port == 9000
        assert host == "0.0.0.0"

    def test_file_overrides_default(self, tmp_path: Path) -> None:
        ws_file = tmp_path / "file_ws"
        ws_file.mkdir()
        resolver = SettingsResolver(
            cli={},
            file_config={
                "server": {"port": 8000},
                "settings": {
                    "workspace": str(ws_file),
                    "scope_batch_size": 50,
                },
            },
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == ws_file.resolve()
        assert settings.scope_batch_size == 50
        _, port = resolver.build_server_bind()
        assert port == 8000

    def test_cli_none_falls_through_to_file(self, tmp_path: Path) -> None:
        ws_file = tmp_path / "file_ws"
        ws_file.mkdir()
        resolver = SettingsResolver(
            cli={"workspace": None},
            file_config={"settings": {"workspace": str(ws_file)}},
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == ws_file.resolve()

    def test_partial_file_config_uses_default_for_missing(self, tmp_path: Path) -> None:
        ws_file = tmp_path / "file_ws"
        ws_file.mkdir()
        resolver = SettingsResolver(
            cli={},
            file_config={"settings": {"workspace": str(ws_file)}},
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == ws_file.resolve()
        # Settings dataclass の default が使われる
        assert settings.scope_batch_size == 100
        assert settings.max_concurrent == 4
        assert settings.allow_origins == []
        assert settings.library_paths == []
        assert settings.bundle_builtin_libraries is True

    def test_empty_resolver_uses_default_workspace(self, tmp_path: Path) -> None:
        resolver = SettingsResolver(cli={}, file_config={})
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == tmp_path
        host, port = resolver.build_server_bind()
        assert host == "127.0.0.1"
        assert port == 8770

    def test_workspace_expanduser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        ws = home / "projA"
        ws.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        resolver = SettingsResolver(
            cli={},
            file_config={"settings": {"workspace": "~/projA"}},
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.workspace_root == ws.resolve()

    def test_library_paths_expanduser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        lib1 = home / "libs"
        lib1.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        ws = tmp_path / "ws"
        ws.mkdir()
        resolver = SettingsResolver(
            cli={"workspace": ws},
            file_config={"settings": {"library_paths": ["~/libs"]}},
        )
        settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.library_paths == [lib1.resolve()]

    def test_type_mismatch_port_raises(self, tmp_path: Path) -> None:
        resolver = SettingsResolver(
            cli={},
            file_config={"server": {"port": "abc"}},
        )
        with pytest.raises(PyflwError, match="port"):
            resolver.build_server_bind()

    def test_type_mismatch_scope_batch_size_raises(self, tmp_path: Path) -> None:
        resolver = SettingsResolver(
            cli={},
            file_config={"settings": {"scope_batch_size": "100"}},
        )
        with pytest.raises(PyflwError, match="scope_batch_size"):
            resolver.build_settings(default_workspace=tmp_path)

    def test_type_mismatch_host_raises(self, tmp_path: Path) -> None:
        resolver = SettingsResolver(
            cli={},
            file_config={"server": {"host": 127}},
        )
        with pytest.raises(PyflwError, match="host"):
            resolver.build_server_bind()

    def test_empty_host_raises(self, tmp_path: Path) -> None:
        """空文字 host は uvicorn で不定挙動になるため明示拒否 (code-reviewer SHOULD)。"""
        resolver = SettingsResolver(
            cli={},
            file_config={"server": {"host": ""}},
        )
        with pytest.raises(PyflwError, match="non-empty"):
            resolver.build_server_bind()

    def test_type_bool_port_raises(self, tmp_path: Path) -> None:
        """bool は int のサブクラスなので明示的に弾く (port = true を許さない)。"""
        resolver = SettingsResolver(
            cli={},
            file_config={"server": {"port": True}},
        )
        with pytest.raises(PyflwError, match="port"):
            resolver.build_server_bind()

    def test_type_bool_scope_batch_size_raises(self, tmp_path: Path) -> None:
        """``_resolve_int_field`` 側も bool を拒否することを保証する。"""
        resolver = SettingsResolver(
            cli={},
            file_config={"settings": {"scope_batch_size": True}},
        )
        with pytest.raises(PyflwError, match="scope_batch_size"):
            resolver.build_settings(default_workspace=tmp_path)

    def test_unknown_key_warns_and_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        # ``_warn_unknown_sections_and_keys`` は ``__init__`` 内で呼ばれるため、
        # caplog の at_level スコープ内で構築する (code-reviewer MUST)。
        with caplog.at_level(logging.WARNING, logger="pyflw.server.config"):
            resolver = SettingsResolver(
                cli={"workspace": ws},
                file_config={
                    "settings": {
                        "scope_batch_size": 50,
                        "scop_batch_size": 999,
                    }
                },
            )
            settings = resolver.build_settings(default_workspace=tmp_path)
        assert settings.scope_batch_size == 50
        assert any("scop_batch_size" in r.message for r in caplog.records)

    def test_unknown_section_warns_and_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # ``_warn_unknown_sections_and_keys`` は ``__init__`` 内で呼ばれるため、
        # caplog の at_level スコープ内で構築する (code-reviewer MUST)。
        with caplog.at_level(logging.WARNING, logger="pyflw.server.config"):
            resolver = SettingsResolver(
                cli={},
                file_config={"experimental": {"foo": 1}},
            )
            resolver.build_settings(default_workspace=tmp_path)
        assert any("experimental" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# generate_config_template
# ---------------------------------------------------------------------------


class TestGenerateConfigTemplate:
    def test_writes_template_to_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        generate_config_template(cfg, force=False)
        assert cfg.is_file()
        content = cfg.read_text(encoding="utf-8")
        # Schema の全フィールドがコメント / 値で含まれる
        assert "[server]" in content
        assert "[settings]" in content
        assert "host" in content
        assert "port" in content
        assert "workspace" in content
        assert "scope_batch_size" in content
        assert "max_concurrent" in content
        assert "allow_origins" in content
        assert "library_paths" in content
        assert "bundle_builtin_libraries" in content

    def test_refuses_existing_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("existing", encoding="utf-8")
        with pytest.raises(PyflwError, match="already exists"):
            generate_config_template(cfg, force=False)
        # 既存内容が保持される
        assert cfg.read_text(encoding="utf-8") == "existing"

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("existing", encoding="utf-8")
        generate_config_template(cfg, force=True)
        assert "[server]" in cfg.read_text(encoding="utf-8")

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / "missing" / "dir" / "config.toml"
        generate_config_template(cfg, force=False)
        assert cfg.is_file()

    def test_generated_template_is_valid_toml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        generate_config_template(cfg, force=False)
        # load し直してもエラーにならない
        parsed = load_config_file(cfg)
        assert "server" in parsed
        assert "settings" in parsed


# ---------------------------------------------------------------------------
# Integration: load_config_file -> SettingsResolver -> Settings
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            "[server]\n"
            'host = "127.0.0.1"\n'
            "port = 8770\n"
            "\n"
            "[settings]\n"
            f'workspace = "{ws.as_posix()}"\n'
            "scope_batch_size = 250\n",
            encoding="utf-8",
        )
        file_cfg = load_config_file(cfg_path)
        resolver = SettingsResolver(cli={}, file_config=file_cfg)
        settings = resolver.build_settings(default_workspace=tmp_path)
        host, port = resolver.build_server_bind()
        assert settings.workspace_root == ws.resolve()
        assert settings.scope_batch_size == 250
        assert isinstance(settings, Settings)
        assert host == "127.0.0.1"
        assert port == 8770
