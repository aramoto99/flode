"""legacy ``--model-dir`` から ``--workspace`` への移行ユーティリティ
(ADR-0041 §論点 6-A)。

``pyflw-server --migrate-models-to=DIR`` で起動するとサーバを起動せず本関数
を実行して終了する。元 ``models/`` 配下の ``*.flw.json`` を非破壊コピーで
移動し、利用者が dst を確認してから src を手動削除する 2-phase 安全フロー
を採用。
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path


@dataclasses.dataclass
class MigrationReport:
    """migrate_models_to の結果レポート。

    Attributes:
        migrated: 正常にコピーされたファイルの **元 path** リスト。
        skipped: dst 既存 + ``force=False`` で skip されたファイルの **元 path** リスト。
        errors: I/O エラーで失敗したファイルの ``(元 path, 例外メッセージ)`` リスト。
    """

    migrated: list[Path] = dataclasses.field(default_factory=list)
    skipped: list[Path] = dataclasses.field(default_factory=list)
    errors: list[tuple[Path, str]] = dataclasses.field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


def migrate_models_to(
    src_dir: Path, dst_dir: Path, *, force: bool = False
) -> MigrationReport:
    """``src_dir`` 配下の ``*.flw.json`` を ``dst_dir`` 配下に非破壊コピーする。

    ADR-0041 §論点 6-A の仕様:
    - ``shutil.copy2`` で mtime 保持
    - 同名ファイルが dst に既存なら ``force=False`` で skip + ``force=True`` で上書き
    - サブディレクトリは **再帰せず** (= ``models/`` フラット構造前提)
    - ``src_dir`` が存在しなければ即 ``MigrationReport(errors=[(src_dir, ...)])``
    - ``dst_dir`` が存在しなければ ``mkdir(parents=True, exist_ok=True)``

    Args:
        src_dir: legacy ``--model-dir`` のディレクトリ (例 ``./models``)。
        dst_dir: 移行先ディレクトリ (= 通常 workspace 配下のサブディレクトリ)。
        force: ``True`` で同名 dst ファイルを上書き、``False`` で skip。

    Returns:
        ``MigrationReport``。``stdout`` への JSON / プレーンテキスト出力は呼び
        出し側 (= ``cli.py``) の責務。
    """
    report = MigrationReport()

    if not src_dir.exists():
        report.errors.append(
            (src_dir, f"Source directory does not exist: {src_dir}")
        )
        return report

    if not src_dir.is_dir():
        report.errors.append(
            (src_dir, f"Source path is not a directory: {src_dir}")
        )
        return report

    dst_dir.mkdir(parents=True, exist_ok=True)

    for src_file in sorted(src_dir.glob("*.flw.json")):
        if not src_file.is_file():
            continue
        dst_file = dst_dir / src_file.name
        if dst_file.exists() and not force:
            report.skipped.append(src_file)
            continue
        try:
            shutil.copy2(src_file, dst_file)
            report.migrated.append(src_file)
        except OSError as e:
            report.errors.append((src_file, str(e)))

    return report
