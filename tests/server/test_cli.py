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
from pytest_mock import MockerFixture

from flode.exceptions import FlodeError
from flode.server.cli import _build_parser, _build_settings_from_args, main


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
# ADR-0080 §A4-1: ライブラリ書き込み API の可否
# ---------------------------------------------------------------------------


class TestLibraryWritePolicy:
    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
    def test_loopback_is_allowed(self, host: str) -> None:
        from flode.server.cli import resolve_library_write_policy

        policy = resolve_library_write_policy(host)
        assert policy.allowed is True
        assert policy.reason == ""

    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "my-laptop.local", ""])
    def test_non_loopback_is_denied(self, host: str) -> None:
        from flode.server.cli import resolve_library_write_policy

        policy = resolve_library_write_policy(host)
        assert policy.allowed is False
        assert "non-loopback" in policy.reason

    def test_no_override_flag_exists(self) -> None:
        """上書きフラグは設けない (ADR-0080 §A4-1)。"""
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["--allow-library-write"])

    @pytest.mark.parametrize(
        ("argv", "expected_allowed"),
        [
            ([], True),
            (["--host", "0.0.0.0"], False),
            (["--host", "0.0.0.0", "--allow-python-blocks"], False),
        ],
    )
    def test_main_passes_policy_and_directory_to_create_app(
        self,
        argv: list[str],
        expected_allowed: bool,
        tmp_path: Path,
        isolated_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        import uvicorn

        from flode.blocks.pythonfunc import set_python_block_policy
        from flode.server import cli

        run = mocker.patch.object(uvicorn, "run")
        mocker.patch.object(cli, "_launch_browser_thread")
        mocker.patch.object(cli, "find_free_port", side_effect=lambda host, port, retries: port)
        monkeypatch.chdir(tmp_path)
        try:
            main(argv)
        finally:
            set_python_block_policy(allowed=True)
        settings = run.call_args.args[0].state.settings
        assert settings.library_write_allowed is expected_allowed
        assert bool(settings.library_write_reason) is not expected_allowed
        # 非 loopback では、既定のユーザーライブラリ (ホーム配下) を読み込まない
        default_dir = (isolated_home / ".flode" / "libraries").resolve()
        assert settings.user_library_dir == (default_dir if expected_allowed else None)
        # 起動しただけではホーム配下に何も作らない
        assert not (isolated_home / ".flode").exists()

    @pytest.mark.parametrize(
        ("host", "explicit", "expect_dir"),
        [
            ("127.0.0.1", False, True),
            ("127.0.0.1", True, True),
            ("0.0.0.0", False, False),  # 既定値での自動読み込みをしない
            ("0.0.0.0", True, True),  # 設定ファイルに明示されていれば読み取り専用で読む
            ("192.168.1.5", False, False),
        ],
    )
    def test_user_library_is_not_scanned_on_non_loopback_unless_explicit(
        self,
        host: str,
        explicit: bool,
        expect_dir: bool,
        tmp_path: Path,
        isolated_home: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        libraries = tmp_path / "libs"
        lines = ["[server]", f'host = "{host}"']
        if explicit:
            lines += ["[settings]", f'user_library_dir = "{libraries.as_posix()}"']
        cfg = isolated_home / ".flode" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with caplog.at_level(logging.INFO, logger="flode.server.cli"):
            settings, resolved_host, *_ = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert resolved_host == host
        expected = libraries.resolve() if explicit else (isolated_home / ".flode" / "libraries")
        assert settings.user_library_dir == (expected.resolve() if expect_dir else None)
        assert settings.library_write_allowed is (host == "127.0.0.1")
        skipped = [r for r in caplog.records if "user library is not loaded" in r.getMessage()]
        assert len(skipped) == (0 if expect_dir else 1)

    def test_explicitly_disabled_user_library_stays_disabled_without_notice(
        self, tmp_path: Path, isolated_home: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        cfg = isolated_home / ".flode" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            '[server]\nhost = "0.0.0.0"\n[settings]\nuser_library_dir = ""\n', encoding="utf-8"
        )
        with caplog.at_level(logging.INFO, logger="flode.server.cli"):
            settings, *_ = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert settings.user_library_dir is None
        assert "user library is not loaded" not in caplog.text

    def test_non_loopback_default_never_serves_my_blocks(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        """既定の置き場にマイブロックがあっても、非 loopback の GET には現れない。"""
        import json

        from fastapi.testclient import TestClient

        from flode.server import create_app
        from tests.server._library_models import library_dict, subsystem_body

        user_file = isolated_home / ".flode" / "libraries" / "user.flwlib.json"
        user_file.parent.mkdir(parents=True)
        user_file.write_text(
            json.dumps(library_dict("user", {"secret": subsystem_body()})), encoding="utf-8"
        )
        for host, visible in (("0.0.0.0", False), ("127.0.0.1", True)):
            settings, *_ = _build_settings_from_args(_make_args(workspace=tmp_path, host=host))
            with TestClient(create_app(settings=settings)) as client:
                listing = client.get("/api/v1/libraries").json()
                detail = client.get("/api/v1/libraries/user/secret")
            assert ("user" in [lib["name"] for lib in listing["libraries"]]) is visible
            assert listing["user_library"]["enabled"] is visible
            assert detail.status_code == (200 if visible else 404)
