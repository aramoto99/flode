"""``migrate_models_to`` の単体テスト (ADR-0041 §論点 6-A)。"""

from __future__ import annotations

from pathlib import Path

from pyflw.server.migrations import MigrationReport, migrate_models_to


def _seed(src: Path, name: str, content: str = "{}") -> Path:
    src.mkdir(parents=True, exist_ok=True)
    p = src / f"{name}.flw.json"
    p.write_text(content, encoding="utf-8")
    return p


class TestMigrateModelsHappyPath:
    def test_copies_flw_json_files(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "workspace"
        _seed(src, "alpha")
        _seed(src, "beta")

        report = migrate_models_to(src, dst)

        assert len(report.migrated) == 2
        assert (dst / "alpha.flw.json").exists()
        assert (dst / "beta.flw.json").exists()
        # 非破壊: src のファイルも残っている
        assert (src / "alpha.flw.json").exists()
        assert (src / "beta.flw.json").exists()
        assert report.errors == []
        assert report.skipped == []

    def test_creates_dst_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "new" / "deep" / "workspace"
        _seed(src, "alpha")

        report = migrate_models_to(src, dst)

        assert dst.is_dir()
        assert len(report.migrated) == 1

    def test_preserves_mtime(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "workspace"
        p = _seed(src, "alpha")
        # mtime を昔に書き換え
        import os

        old_mtime = 1_000_000_000.0  # 2001-09-09
        os.utime(p, (old_mtime, old_mtime))

        migrate_models_to(src, dst)
        assert (dst / "alpha.flw.json").stat().st_mtime == old_mtime


class TestMigrateModelsConflict:
    def test_skips_existing_dst_without_force(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "workspace"
        _seed(src, "alpha", "src content")
        dst.mkdir()
        (dst / "alpha.flw.json").write_text("dst content", encoding="utf-8")

        report = migrate_models_to(src, dst)

        assert len(report.skipped) == 1
        assert report.skipped[0].name == "alpha.flw.json"
        assert report.migrated == []
        # dst の中身は変わらない
        assert (dst / "alpha.flw.json").read_text(encoding="utf-8") == "dst content"

    def test_overwrites_with_force(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "workspace"
        _seed(src, "alpha", "src content")
        dst.mkdir()
        (dst / "alpha.flw.json").write_text("dst content", encoding="utf-8")

        report = migrate_models_to(src, dst, force=True)

        assert len(report.migrated) == 1
        assert report.skipped == []
        assert (dst / "alpha.flw.json").read_text(encoding="utf-8") == "src content"


class TestMigrateModelsErrors:
    def test_nonexistent_src_returns_error(self, tmp_path: Path) -> None:
        src = tmp_path / "ghost"
        dst = tmp_path / "workspace"
        report = migrate_models_to(src, dst)
        assert report.has_errors
        assert "does not exist" in report.errors[0][1]

    def test_src_is_file_returns_error(self, tmp_path: Path) -> None:
        src = tmp_path / "not_a_dir.txt"
        src.write_text("hello")
        dst = tmp_path / "workspace"
        report = migrate_models_to(src, dst)
        assert report.has_errors
        assert "not a directory" in report.errors[0][1]

    def test_non_flw_json_files_are_ignored(self, tmp_path: Path) -> None:
        src = tmp_path / "models"
        dst = tmp_path / "workspace"
        _seed(src, "alpha")
        # ``.flw.json`` 以外のファイルは migrate 対象外
        (src / "readme.txt").write_text("ignored", encoding="utf-8")
        (src / "data.json").write_text("ignored", encoding="utf-8")

        report = migrate_models_to(src, dst)
        assert len(report.migrated) == 1
        assert (dst / "alpha.flw.json").exists()
        assert not (dst / "readme.txt").exists()
        assert not (dst / "data.json").exists()


class TestMigrationReport:
    def test_default_fields(self) -> None:
        r = MigrationReport()
        assert r.migrated == []
        assert r.skipped == []
        assert r.errors == []
        assert r.has_errors is False

    def test_has_errors_true_with_errors(self) -> None:
        r = MigrationReport(errors=[(Path("x"), "msg")])
        assert r.has_errors is True
