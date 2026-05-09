"""``pyflw-server`` CLI の引数解析と Settings 構築テスト (ADR-0041 §3)。

``main()`` は uvicorn を起動するため直接テストせず、``_build_parser`` /
``_build_settings`` の組み合わせで検証する。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from pyflw.exceptions import PyflwError
from pyflw.server.cli import _build_parser, _build_settings, main

# ---------------------------------------------------------------------------
# argparse: mutual exclusion
# ---------------------------------------------------------------------------


class TestParserMutualExclusion:
    def test_workspace_and_model_dir_together_exits(self, tmp_path: Path) -> None:
        """``--workspace`` と ``--model-dir`` 両指定で SystemExit (= argparse エラー)。"""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--workspace", str(tmp_path), "--model-dir", str(tmp_path)]
            )

    def test_workspace_alone_parses(self, tmp_path: Path) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--workspace", str(tmp_path)])
        assert args.workspace == tmp_path
        assert args.model_dir is None

    def test_model_dir_alone_parses(self, tmp_path: Path) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--model-dir", str(tmp_path)])
        assert args.model_dir == tmp_path
        assert args.workspace is None

    def test_neither_specified_defaults_to_none(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.workspace is None
        assert args.model_dir is None


# ---------------------------------------------------------------------------
# _build_settings: --workspace mode
# ---------------------------------------------------------------------------


class TestBuildSettingsWorkspaceMode:
    def test_workspace_sets_both_workspace_root_and_model_dir(self, tmp_path: Path) -> None:
        settings = _build_settings(
            workspace=tmp_path,
            model_dir=None,
            allow_origins=[],
            scope_batch_size=100,
        )
        assert settings.workspace_root == tmp_path.resolve()
        assert settings.model_dir == tmp_path.resolve()

    def test_workspace_resolves_to_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 相対 path で渡しても Settings には絶対 path が入る。
        # ``monkeypatch.chdir`` でテスト終了時に CWD が自動復元される (= xdist 安全)。
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ws").mkdir()
        settings = _build_settings(
            workspace=Path("ws"),
            model_dir=None,
            allow_origins=[],
            scope_batch_size=100,
        )
        assert settings.workspace_root == (tmp_path / "ws").resolve()
        assert settings.workspace_root is not None
        assert settings.workspace_root.is_absolute()

    def test_workspace_does_not_emit_deprecation_warning(self, tmp_path: Path) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # warnings → exception
            _build_settings(
                workspace=tmp_path,
                model_dir=None,
                allow_origins=[],
                scope_batch_size=100,
            )


class TestBuildSettingsWorkspaceErrors:
    def test_workspace_nonexistent_raises(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(PyflwError, match="does not exist"):
            _build_settings(
                workspace=nonexistent,
                model_dir=None,
                allow_origins=[],
                scope_batch_size=100,
            )

    def test_workspace_is_file_not_directory_raises(self, tmp_path: Path) -> None:
        a_file = tmp_path / "regular.txt"
        a_file.write_text("hello")
        with pytest.raises(PyflwError, match="not a directory"):
            _build_settings(
                workspace=a_file,
                model_dir=None,
                allow_origins=[],
                scope_batch_size=100,
            )


# ---------------------------------------------------------------------------
# _build_settings: legacy --model-dir mode
# ---------------------------------------------------------------------------


class TestBuildSettingsLegacyModelDir:
    def test_model_dir_emits_deprecation_warning(self, tmp_path: Path) -> None:
        with pytest.warns(DeprecationWarning, match="--model-dir is deprecated"):
            _build_settings(
                workspace=None,
                model_dir=tmp_path,
                allow_origins=[],
                scope_batch_size=100,
            )

    def test_model_dir_sets_workspace_root_to_none(self, tmp_path: Path) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            settings = _build_settings(
                workspace=None,
                model_dir=tmp_path,
                allow_origins=[],
                scope_batch_size=100,
            )
        # File API 無効化を表す sentinel
        assert settings.workspace_root is None
        assert settings.model_dir == tmp_path

    def test_model_dir_nonexistent_does_not_raise(self, tmp_path: Path) -> None:
        # legacy 互換: --model-dir が不在でも ``create_app`` 内 mkdir で作成される
        # (= 旧挙動を維持)。本関数では検証しない。
        nonexistent = tmp_path / "does-not-exist"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            settings = _build_settings(
                workspace=None,
                model_dir=nonexistent,
                allow_origins=[],
                scope_batch_size=100,
            )
        assert settings.model_dir == nonexistent


# ---------------------------------------------------------------------------
# _build_settings: default (= 両方未指定)
# ---------------------------------------------------------------------------


class TestBuildSettingsDefault:
    """両方未指定時は default ``--workspace=Path.cwd()``。

    ``monkeypatch.chdir`` でテスト中の CWD を制御し、終了時に自動復元する
    (= xdist worker safe)。
    """

    def test_default_uses_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings = _build_settings(
            workspace=None,
            model_dir=None,
            allow_origins=[],
            scope_batch_size=100,
        )
        assert settings.workspace_root == tmp_path.resolve()
        assert settings.model_dir == tmp_path.resolve()

    def test_default_does_not_emit_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _build_settings(
                workspace=None,
                model_dir=None,
                allow_origins=[],
                scope_batch_size=100,
            )


# ---------------------------------------------------------------------------
# allow_origins / scope_batch_size の伝搬
# ---------------------------------------------------------------------------


class TestBuildSettingsOtherFields:
    def test_allow_origins_propagated(self, tmp_path: Path) -> None:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        settings = _build_settings(
            workspace=tmp_path,
            model_dir=None,
            allow_origins=origins,
            scope_batch_size=100,
        )
        assert settings.allow_origins == origins

    def test_scope_batch_size_propagated(self, tmp_path: Path) -> None:
        settings = _build_settings(
            workspace=tmp_path,
            model_dir=None,
            allow_origins=[],
            scope_batch_size=42,
        )
        assert settings.scope_batch_size == 42


# ---------------------------------------------------------------------------
# create_app integration
# ---------------------------------------------------------------------------


class TestCreateAppIntegration:
    """``create_app`` が ``workspace_root`` を ``app.state.settings`` で公開する。"""

    def test_workspace_root_propagates_to_app_state(self, tmp_path: Path) -> None:
        from pyflw.server import create_app

        settings = _build_settings(
            workspace=tmp_path,
            model_dir=None,
            allow_origins=[],
            scope_batch_size=100,
        )
        app = create_app(settings.model_dir, settings=settings)
        assert app.state.settings.workspace_root == tmp_path.resolve()
        assert app.state.settings.model_dir == tmp_path.resolve()

    def test_legacy_model_dir_workspace_root_is_none(self, tmp_path: Path) -> None:
        from pyflw.server import create_app

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            settings = _build_settings(
                workspace=None,
                model_dir=tmp_path / "models",
                allow_origins=[],
                scope_batch_size=100,
            )
        app = create_app(settings.model_dir, settings=settings)
        assert app.state.settings.workspace_root is None
        assert app.state.settings.model_dir == tmp_path / "models"


# ---------------------------------------------------------------------------
# main() smoke test (= uvicorn は起動しない、import error path のみ検証)
# ---------------------------------------------------------------------------


class TestMainErrorPaths:
    def test_main_with_nonexistent_workspace_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(PyflwError, match="does not exist"):
            main(["--workspace", str(nonexistent)])
