"""``flode`` CLI の引数解析と Settings 構築テスト (ADR-0041 §3 / SPEC-0004)。

``main()`` は uvicorn を起動するため直接テストせず、``_build_parser`` /
``_build_settings_from_args`` の組み合わせで検証する。

v0.21.0: legacy ``--model-dir`` 関連テストを削除、``--migrate-models-to`` /
``--legacy-models-dir`` の path-only mode テストを追加。
SPEC-0004: 設定ファイル機能は ``test_config.py`` / ``test_cli_with_config.py`` でカバー。
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from flode.exceptions import FlodeError
from flode.server.cli import (
    _build_parser,
    _build_settings_from_args,
    main,
    resolve_user_block_policy,
)


def _make_args(**overrides: object) -> argparse.Namespace:
    """argparse Namespace の最小フィクスチャ (全フラグ None / False で初期化)。"""
    base = {
        "workspace": None,
        "host": None,
        "port": None,
        "allow_origin": None,
        "scope_batch_size": None,
        "config": None,
        "generate_config": False,
        "migrate_models_to": None,
        "legacy_models_dir": None,
        "force": False,
        "no_browser": False,
        "allow_python_blocks": False,
        "allow_user_blocks": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


# ``isolated_home`` fixture は tests/server/conftest.py で共有。


# ---------------------------------------------------------------------------
# argparse: --workspace / --migrate-models-to / SPEC-0004 フラグ
# ---------------------------------------------------------------------------


class TestParser:
    def test_workspace_alone_parses(self, tmp_path: Path) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--workspace", str(tmp_path)])
        assert args.workspace == tmp_path
        assert args.migrate_models_to is None

    def test_no_args_defaults_to_none(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.workspace is None
        assert args.host is None
        assert args.port is None
        assert args.allow_origin is None
        assert args.scope_batch_size is None
        assert args.config is None
        assert args.generate_config is False
        assert args.migrate_models_to is None
        assert args.legacy_models_dir is None
        assert args.force is False

    def test_migrate_args_parse(self, tmp_path: Path) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--migrate-models-to",
                str(tmp_path / "ws"),
                "--legacy-models-dir",
                str(tmp_path / "models"),
                "--force",
            ]
        )
        assert args.migrate_models_to == tmp_path / "ws"
        assert args.legacy_models_dir == tmp_path / "models"
        assert args.force is True

    def test_model_dir_arg_no_longer_recognized(self) -> None:
        """v0.21.0: ``--model-dir`` 引数は削除済 → argparse がエラーを出す。"""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--model-dir", "./models"])

    def test_config_flag_parses(self, tmp_path: Path) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--config", str(tmp_path / "my.toml")])
        assert args.config == tmp_path / "my.toml"

    def test_generate_config_flag_parses(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--generate-config"])
        assert args.generate_config is True


# ---------------------------------------------------------------------------
# _build_settings_from_args: --workspace mode
# ---------------------------------------------------------------------------


class TestBuildSettingsWorkspaceMode:
    def test_workspace_sets_workspace_root(self, tmp_path: Path, isolated_home: Path) -> None:
        settings, _, _, _, _, _ = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert settings.workspace_root == tmp_path.resolve()

    def test_workspace_resolves_to_absolute(
        self,
        tmp_path: Path,
        isolated_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ws").mkdir()
        settings, _, _, _, _, _ = _build_settings_from_args(_make_args(workspace=Path("ws")))
        assert settings.workspace_root == (tmp_path / "ws").resolve()
        assert settings.workspace_root.is_absolute()

    def test_no_deprecation_warning_emitted(self, tmp_path: Path, isolated_home: Path) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _build_settings_from_args(_make_args(workspace=tmp_path))


class TestBuildSettingsWorkspaceErrors:
    def test_workspace_nonexistent_raises(self, tmp_path: Path, isolated_home: Path) -> None:
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(FlodeError, match="does not exist"):
            _build_settings_from_args(_make_args(workspace=nonexistent))

    def test_workspace_is_file_not_directory_raises(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        a_file = tmp_path / "regular.txt"
        a_file.write_text("hello")
        with pytest.raises(FlodeError, match="not a directory"):
            _build_settings_from_args(_make_args(workspace=a_file))


# ---------------------------------------------------------------------------
# _build_settings_from_args: default (= --workspace 未指定)
# ---------------------------------------------------------------------------


class TestBuildSettingsDefault:
    def test_default_uses_cwd(
        self,
        tmp_path: Path,
        isolated_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings, host, port, _, _, _ = _build_settings_from_args(_make_args())
        assert settings.workspace_root == tmp_path.resolve()
        assert host == "127.0.0.1"
        assert port == 8770


# ---------------------------------------------------------------------------
# allow_origins / scope_batch_size の伝搬
# ---------------------------------------------------------------------------


class TestBuildSettingsOtherFields:
    def test_allow_origin_propagated(self, tmp_path: Path, isolated_home: Path) -> None:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        settings, _, _, _, _, _ = _build_settings_from_args(
            _make_args(workspace=tmp_path, allow_origin=origins)
        )
        assert settings.allow_origins == origins

    def test_scope_batch_size_propagated(self, tmp_path: Path, isolated_home: Path) -> None:
        settings, _, _, _, _, _ = _build_settings_from_args(
            _make_args(workspace=tmp_path, scope_batch_size=42)
        )
        assert settings.scope_batch_size == 42

    def test_host_port_propagated(self, tmp_path: Path, isolated_home: Path) -> None:
        _, host, port, _, _, _ = _build_settings_from_args(
            _make_args(workspace=tmp_path, host="0.0.0.0", port=9000)
        )
        assert host == "0.0.0.0"
        assert port == 9000


# ---------------------------------------------------------------------------
# create_app integration
# ---------------------------------------------------------------------------


class TestCreateAppIntegration:
    """``create_app`` が ``workspace_root`` を ``app.state.settings`` で公開する。"""

    def test_workspace_root_propagates_to_app_state(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        from flode.server import create_app

        settings, _, _, _, _, _ = _build_settings_from_args(_make_args(workspace=tmp_path))
        app = create_app(settings=settings)
        assert app.state.settings.workspace_root == tmp_path.resolve()


# ---------------------------------------------------------------------------
# main() smoke test
# ---------------------------------------------------------------------------


class TestMainErrorPaths:
    def test_main_with_nonexistent_workspace_raises(
        self,
        tmp_path: Path,
        isolated_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(FlodeError, match="does not exist"):
            main(["--workspace", str(nonexistent)])

    def test_main_migrate_models_to_without_src_exits_with_code_2(
        self,
        tmp_path: Path,
        isolated_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--migrate-models-to`` 単体 (= ``--legacy-models-dir`` なし) で終了
        コード 2、サーバ起動しない。"""
        with pytest.raises(SystemExit) as exc_info:
            main(["--migrate-models-to", str(tmp_path / "ws")])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "--legacy-models-dir" in captured.err

    def test_main_migrate_models_to_executes_and_exits(
        self,
        tmp_path: Path,
        isolated_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """正常系: src + dst 指定で migrate を実行 + 結果を JSON で stdout 出力。"""
        src = tmp_path / "models"
        dst = tmp_path / "ws"
        src.mkdir()
        (src / "alpha.flw.json").write_text("{}", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "--migrate-models-to",
                    str(dst),
                    "--legacy-models-dir",
                    str(src),
                ]
            )
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        # JSON 出力が含まれているか
        assert '"migrated"' in captured.out
        assert (dst / "alpha.flw.json").exists()


# ---------------------------------------------------------------------------
# SPEC-0023 / ADR-0073 §論点 4 (H): PythonFunction hard gate
# ---------------------------------------------------------------------------


class TestPythonBlockPolicy:
    def test_flag_parses(self) -> None:
        args = _build_parser().parse_args(["--allow-python-blocks"])
        assert args.allow_python_blocks is True
        assert _build_parser().parse_args([]).allow_python_blocks is False

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("localhost", True),
            ("LOCALHOST", True),
            ("127.0.0.1", True),
            ("127.1.2.3", True),
            ("::1", True),
            ("[::1]", True),
            ("0.0.0.0", False),
            ("::", False),
            ("192.168.1.5", False),
            ("my-laptop.local", False),  # 解析不能なホスト名は fail closed
            ("", False),
        ],
    )
    def test_is_loopback_host_table(self, host: str, expected: bool) -> None:
        from flode.server.cli import is_loopback_host

        assert is_loopback_host(host) is expected

    def test_policy_loopback_always_allowed(self) -> None:
        from flode.server.cli import resolve_python_block_policy

        p = resolve_python_block_policy("127.0.0.1", cli_flag=False, file_allow=False)
        assert p.allowed is True

    def test_policy_non_loopback_denied_without_flag(self) -> None:
        from flode.server.cli import resolve_python_block_policy

        p = resolve_python_block_policy("0.0.0.0", cli_flag=False, file_allow=False)
        assert p.allowed is False
        assert "0.0.0.0" in p.reason
        assert "--allow-python-blocks" in p.reason

    @pytest.mark.parametrize(("cli_flag", "file_allow"), [(True, False), (False, True)])
    def test_policy_non_loopback_allowed_with_flag(self, cli_flag: bool, file_allow: bool) -> None:
        from flode.server.cli import resolve_python_block_policy

        p = resolve_python_block_policy("0.0.0.0", cli_flag=cli_flag, file_allow=file_allow)
        assert p.allowed is True

    def test_allow_flag_propagates_from_cli(self, tmp_path: Path, isolated_home: Path) -> None:
        *_, allow = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert allow is False
        args = _build_parser().parse_args(["--workspace", str(tmp_path), "--allow-python-blocks"])
        *_, allow = _build_settings_from_args(args)
        assert allow is True


# ---------------------------------------------------------------------------
# ADR-0081 §論点 6: ユーザーブロックの policy (--allow-user-blocks / [blocks])
# ---------------------------------------------------------------------------


def _write_config(home: Path, text: str) -> None:
    cfg = home / ".flode" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text, encoding="utf-8")


class TestUserBlockPolicy:
    def test_flag_parses(self) -> None:
        assert _build_parser().parse_args(["--allow-user-blocks"]).allow_user_blocks is True
        assert _build_parser().parse_args([]).allow_user_blocks is False

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
    def test_loopback_reads_and_reloads(self, host: str) -> None:
        p = resolve_user_block_policy(host, cli_flag=False, file_allow=False)
        assert (p.enabled, p.reload_allowed, p.reason) == (True, True, "")

    def test_non_loopback_without_permission_does_not_read(self) -> None:
        p = resolve_user_block_policy("0.0.0.0", cli_flag=False, file_allow=False)
        assert (p.enabled, p.reload_allowed) == (False, False)
        assert "0.0.0.0" in p.reason
        assert "--allow-user-blocks" in p.reason

    @pytest.mark.parametrize(("cli_flag", "file_allow"), [(True, False), (False, True)])
    def test_non_loopback_with_permission_reads_without_reload(
        self, cli_flag: bool, file_allow: bool
    ) -> None:
        p = resolve_user_block_policy("0.0.0.0", cli_flag=cli_flag, file_allow=file_allow)
        assert (p.enabled, p.reload_allowed) == (True, False)

    def test_loopback_settings_carry_load_request(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        settings, *_ = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert settings.user_blocks_enabled is True
        assert settings.user_blocks_reload_allowed is True
        assert settings.loopback_bind is True
        request = settings.user_blocks_request
        assert request is not None
        assert request.workspace == tmp_path.resolve()
        assert request.workspace_from_cwd is False
        assert (request.dirs, request.modules) == ((), ())

    def test_cwd_workspace_is_marked(
        self, tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings, *_ = _build_settings_from_args(_make_args())
        assert settings.user_blocks_request is not None
        assert settings.user_blocks_request.workspace_from_cwd is True

    def test_config_workspace_is_not_cwd(self, tmp_path: Path, isolated_home: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_config(isolated_home, f"[settings]\nworkspace = {ws.as_posix()!r}\n")
        settings, *_ = _build_settings_from_args(_make_args())
        assert settings.user_blocks_request is not None
        assert settings.user_blocks_request.workspace_from_cwd is False

    def test_non_loopback_default_disables(self, tmp_path: Path, isolated_home: Path) -> None:
        settings, *_ = _build_settings_from_args(_make_args(workspace=tmp_path, host="0.0.0.0"))
        assert settings.user_blocks_enabled is False
        # 読まないが、files API で守るルートの計算のために request は入る
        assert settings.user_blocks_request is not None
        assert settings.loopback_bind is False
        assert "--allow-user-blocks" in settings.user_blocks_reason

    def test_allow_python_blocks_does_not_enable_user_blocks(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        settings, *_ = _build_settings_from_args(
            _make_args(workspace=tmp_path, host="0.0.0.0", allow_python_blocks=True)
        )
        assert settings.user_blocks_enabled is False

    def test_allow_user_blocks_flag(self, tmp_path: Path, isolated_home: Path) -> None:
        settings, *_ = _build_settings_from_args(
            _make_args(workspace=tmp_path, host="0.0.0.0", allow_user_blocks=True)
        )
        assert settings.user_blocks_enabled is True
        assert settings.user_blocks_reload_allowed is False
        assert settings.loopback_bind is False

    def test_config_section_is_applied(self, tmp_path: Path, isolated_home: Path) -> None:
        (isolated_home / ".flode" / "lab").mkdir(parents=True)
        _write_config(
            isolated_home,
            '[blocks]\ndirs = { lab = "lab" }\nmodules = ["mypkg.blocks"]\n'
            "allow_non_loopback = true\n",
        )
        settings, *_ = _build_settings_from_args(_make_args(workspace=tmp_path, host="0.0.0.0"))
        assert settings.user_blocks_enabled is True
        request = settings.user_blocks_request
        assert request is not None
        # dirs の相対パスは config ファイルのフォルダ基準
        assert request.dirs == (("lab", (isolated_home / ".flode" / "lab").resolve()),)
        assert request.modules == ("mypkg.blocks",)

    def test_config_type_violation_is_startup_error(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        _write_config(isolated_home, '[blocks]\nmodules = "mypkg"\n')
        with pytest.raises(FlodeError, match="modules"):
            _build_settings_from_args(_make_args(workspace=tmp_path))


_CLI_PROBE = (
    "from flode import block\n\n\n"
    "@block\n"
    "def cli_probe(t: float, u: float, *, k: float = 1.0) -> float:\n"
    "    return k * u\n"
)


class TestMainLoadsUserBlocks:
    """``main()`` 経由の起動で lifespan がユーザーブロックを読む (uvicorn は mock)。"""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "blocks").mkdir(parents=True)
        (ws / "blocks" / "probe.py").write_text(_CLI_PROBE, encoding="utf-8")
        return ws

    @staticmethod
    def _started_app(mocker: MockerFixture, argv: list[str]) -> FastAPI:
        import uvicorn

        from flode.server import cli

        mocker.patch.object(cli, "_launch_browser_thread")
        mocker.patch.object(cli, "find_free_port", side_effect=lambda host, port, retries: port)
        run = mocker.patch.object(uvicorn, "run")
        main([*argv, "--no-browser"])
        app: FastAPI = run.call_args.args[0]
        return app

    @staticmethod
    def _user_types(app: FastAPI) -> list[str]:
        with TestClient(app) as client:
            body = client.get("/api/v1/blocks").json()
        return [b["type_path"] for b in body["blocks"] if b["source"] != "builtin"]

    def test_loopback_reads_blocks(
        self, workspace: Path, isolated_home: Path, mocker: MockerFixture
    ) -> None:
        app = self._started_app(mocker, ["--workspace", str(workspace)])
        assert self._user_types(app) == ["flode_ws.probe.CliProbe"]

    def test_cwd_workspace_reads_blocks(
        self,
        workspace: Path,
        isolated_home: Path,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(workspace)
        app = self._started_app(mocker, [])
        assert app.state.settings.user_blocks_request.workspace_from_cwd is True
        assert self._user_types(app) == ["flode_ws.probe.CliProbe"]

    def test_non_loopback_default_does_not_read(
        self, workspace: Path, isolated_home: Path, mocker: MockerFixture
    ) -> None:
        app = self._started_app(mocker, ["--workspace", str(workspace), "--host", "0.0.0.0"])
        assert self._user_types(app) == []

    def test_non_loopback_with_flag_reads(
        self, workspace: Path, isolated_home: Path, mocker: MockerFixture
    ) -> None:
        app = self._started_app(
            mocker,
            ["--workspace", str(workspace), "--host", "0.0.0.0", "--allow-user-blocks"],
        )
        assert self._user_types(app) == ["flode_ws.probe.CliProbe"]

    def test_non_loopback_with_config_permission_reads(
        self, workspace: Path, isolated_home: Path, mocker: MockerFixture
    ) -> None:
        _write_config(isolated_home, "[blocks]\nallow_non_loopback = true\n")
        app = self._started_app(mocker, ["--workspace", str(workspace), "--host", "0.0.0.0"])
        assert self._user_types(app) == ["flode_ws.probe.CliProbe"]
