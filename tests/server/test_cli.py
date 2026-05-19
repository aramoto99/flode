"""``pyflw-server`` CLI の引数解析と Settings 構築テスト (ADR-0041 §3 / SPEC-0004)。

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

from pyflw.exceptions import PyflwError
from pyflw.server.cli import _build_parser, _build_settings_from_args, main


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
    def test_workspace_sets_workspace_root(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        settings, _, _ = _build_settings_from_args(_make_args(workspace=tmp_path))
        assert settings.workspace_root == tmp_path.resolve()

    def test_workspace_resolves_to_absolute(
        self,
        tmp_path: Path,
        isolated_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ws").mkdir()
        settings, _, _ = _build_settings_from_args(_make_args(workspace=Path("ws")))
        assert settings.workspace_root == (tmp_path / "ws").resolve()
        assert settings.workspace_root.is_absolute()

    def test_no_deprecation_warning_emitted(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _build_settings_from_args(_make_args(workspace=tmp_path))


class TestBuildSettingsWorkspaceErrors:
    def test_workspace_nonexistent_raises(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(PyflwError, match="does not exist"):
            _build_settings_from_args(_make_args(workspace=nonexistent))

    def test_workspace_is_file_not_directory_raises(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        a_file = tmp_path / "regular.txt"
        a_file.write_text("hello")
        with pytest.raises(PyflwError, match="not a directory"):
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
        settings, host, port = _build_settings_from_args(_make_args())
        assert settings.workspace_root == tmp_path.resolve()
        assert host == "127.0.0.1"
        assert port == 8770


# ---------------------------------------------------------------------------
# allow_origins / scope_batch_size の伝搬
# ---------------------------------------------------------------------------


class TestBuildSettingsOtherFields:
    def test_allow_origin_propagated(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        settings, _, _ = _build_settings_from_args(
            _make_args(workspace=tmp_path, allow_origin=origins)
        )
        assert settings.allow_origins == origins

    def test_scope_batch_size_propagated(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        settings, _, _ = _build_settings_from_args(
            _make_args(workspace=tmp_path, scope_batch_size=42)
        )
        assert settings.scope_batch_size == 42

    def test_host_port_propagated(
        self, tmp_path: Path, isolated_home: Path
    ) -> None:
        _, host, port = _build_settings_from_args(
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
        from pyflw.server import create_app

        settings, _, _ = _build_settings_from_args(_make_args(workspace=tmp_path))
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
        with pytest.raises(PyflwError, match="does not exist"):
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
