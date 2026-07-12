"""``pyflw-server`` CLI + 設定ファイル (SPEC-0004) の統合テスト。

``main()`` の uvicorn 起動経路を mock し、Settings / bind が CLI > file > default の
優先順位通りに解決されることを確認する。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from pyflw.exceptions import PyflwError
from pyflw.server.cli import main

# ``isolated_home`` fixture は tests/server/conftest.py で共有。


@pytest.fixture
def mock_uvicorn(mocker: MockerFixture) -> object:
    """``uvicorn.run`` を mock してサーバ起動を抑止する。"""
    import uvicorn

    return mocker.patch.object(uvicorn, "run")


@pytest.fixture(autouse=True)
def suppress_startup_side_effects(mocker: MockerFixture) -> None:
    """SPEC-0021 の起動シーケンスを本モジュールでは無効化する。

    - ``_launch_browser_thread``: 実ブラウザを開かせない
    - ``find_free_port``: 実 socket プローブを行わず要求ポートをそのまま返す
      (開発機で 8770 等が偶然使用中でも port の assert が壊れないよう決定化)。
    起動 UX 自体のテストは ``test_cli_startup.py`` が担う。
    """
    from pyflw.server import cli

    mocker.patch.object(cli, "_launch_browser_thread")
    mocker.patch.object(cli, "find_free_port", side_effect=lambda host, port, retries: port)


class TestCliWithConfigFile:
    def test_no_config_starts_with_defaults(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # SPEC-0004 §7: 設定ファイル不在時は WARNING ログを出さず default で起動する
        # (リファレンス Web IDE 準拠の lenient な不在処理)。
        with caplog.at_level(logging.WARNING, logger="pyflw.server.config"):
            main([])
        warning_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name.startswith("pyflw.server.config")
        ]
        assert not warning_records, f"Unexpected warnings: {warning_records}"
        mock_uvicorn.assert_called_once()
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8770
        app = mock_uvicorn.call_args.args[0]
        assert app.state.settings.workspace_root == tmp_path.resolve()

    def test_config_file_applies_settings(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            "[server]\n"
            'host = "0.0.0.0"\n'
            "port = 9100\n"
            "\n"
            "[settings]\n"
            f'workspace = "{ws.as_posix()}"\n'
            "scope_batch_size = 250\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        main([])
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9100
        app = mock_uvicorn.call_args.args[0]
        assert app.state.settings.workspace_root == ws.resolve()
        assert app.state.settings.scope_batch_size == 250

    def test_explicit_config_flag(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        explicit = tmp_path / "alt.toml"
        explicit.write_text(
            f'[server]\nport = 9200\n[settings]\nworkspace = "{ws.as_posix()}"\n',
            encoding="utf-8",
        )
        # 暗黙探索の方には 9100 を書いておく → 明示 --config が優先されることを確認
        default_cfg = isolated_home / ".pyflw" / "config.toml"
        default_cfg.parent.mkdir(parents=True)
        default_cfg.write_text(
            f'[server]\nport = 9100\n[settings]\nworkspace = "{ws.as_posix()}"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        main(["--config", str(explicit)])
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 9200

    def test_cli_arg_overrides_config(
        self,
        tmp_path: Path,
        isolated_home: Path,
        mock_uvicorn,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            f'[server]\nport = 9100\n[settings]\nworkspace = "{ws.as_posix()}"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        main(["--port", "9999"])
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 9999  # CLI が file の 9100 を上書き

    def test_explicit_missing_config_raises(
        self,
        tmp_path: Path,
        isolated_home: Path,
    ) -> None:
        with pytest.raises(PyflwError, match="does not exist"):
            main(["--config", str(tmp_path / "nope.toml")])


class TestGenerateConfigCli:
    def test_generate_config_writes_to_user_home(
        self,
        isolated_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--generate-config"])
        assert exc_info.value.code == 0
        cfg = isolated_home / ".pyflw" / "config.toml"
        assert cfg.is_file()
        content = cfg.read_text(encoding="utf-8")
        assert "[server]" in content
        assert "[settings]" in content

    def test_generate_config_refuses_existing_without_force(
        self,
        isolated_home: Path,
    ) -> None:
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("existing", encoding="utf-8")
        with pytest.raises(PyflwError, match="already exists"):
            main(["--generate-config"])

    def test_generate_config_force_overwrites(
        self,
        isolated_home: Path,
    ) -> None:
        cfg = isolated_home / ".pyflw" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("existing", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(["--generate-config", "--force"])
        assert exc_info.value.code == 0
        assert "[server]" in cfg.read_text(encoding="utf-8")
