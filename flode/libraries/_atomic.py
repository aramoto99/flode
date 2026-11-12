"""``.flwlib.json`` のアトミック書き込み (ADR-0080 §A6-1)。

書き込み途中のクラッシュや他プロセスとの競合でライブラリファイルが壊れないよう、
次の順で置換する:

  1. 同じディレクトリの一時ファイルに新しい内容を書き、``flush`` → ``fsync`` する
  2. 既存ファイルがあれば、その内容を同じ手順 (一時ファイル → ``os.replace``) で
     ``<name>.bak`` に退避する
  3. ``os.replace`` で一時ファイルを書き込み先に置換する

2 → 3 の間でクラッシュしても 「書き込み先 = 旧内容、``.bak`` = 旧内容」 で整合する
(先に書き込み先を ``.bak`` へ move する方式は、途中で書き込み先が消える窓がある)。

一時ファイル・``.bak`` の名前は ``*.flwlib.json`` で終わらないので、ライブラリの
探索 (``*.flwlib.json`` の glob) に拾われない。

.. note::

   本 module はパッケージ内部実装。外部からは ``flode.libraries.atomic_write_text``
   を使うこと。
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from pathlib import Path

from ..exceptions import LibraryWriteBusyError, LibraryWriteError

_logger = logging.getLogger("flode.libraries")

#: ``os.replace`` の最大試行回数 (初回を含む)。
REPLACE_MAX_ATTEMPTS = 5
#: 再試行前の待ち時間の起点 [s]。失敗のたびに ``REPLACE_BACKOFF_FACTOR`` 倍する。
REPLACE_INITIAL_BACKOFF_SECONDS = 0.05
#: 指数バックオフの倍率。
REPLACE_BACKOFF_FACTOR = 2.0
#: 直前の内容を退避するバックアップファイルの接尾辞 (1 世代)。
BACKUP_SUFFIX = ".bak"

_TEMP_SUFFIX = ".tmp"
_TEMP_TOKEN_BYTES = 8
_ENCODING = "utf-8"

# 他プロセスがファイルを開いていると ``os.replace`` が ``PermissionError`` になるのは
# Windows 固有の挙動。POSIX の ``PermissionError`` は本当の権限不足なので、再試行
# せず即失敗させる (待っても直らないものを 「一時的に busy」 と誤分類しない)。
_RETRY_PERMISSION_ERRORS = sys.platform == "win32"


def backup_path_for(path: str | Path) -> Path:
    """``path`` のバックアップファイル (``<name>.bak``) の path を返す。

    Args:
        path: 書き込み先ファイルの path。

    Returns:
        同じディレクトリの ``<ファイル名>.bak``。
    """
    p = Path(path)
    return p.with_name(p.name + BACKUP_SUFFIX)


def _write_temp_file(target: Path, data: bytes) -> Path:
    """``target`` と同じディレクトリに一時ファイルを作り、``data`` を書いて fsync する。"""
    token = secrets.token_hex(_TEMP_TOKEN_BYTES)
    temp = target.with_name(f".{target.name}.{token}{_TEMP_SUFFIX}")
    # "x" (排他作成): 万一名前が衝突しても既存ファイルを上書きしない
    with open(temp, "xb") as f:
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except OSError:
            f.close()
            _remove_quietly(temp)
            raise
    return temp


def _remove_quietly(path: Path) -> None:
    """一時ファイルを消す。消せなくても元の失敗を上書きしない (ログに残す)。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        _logger.warning("atomic write: could not remove temporary file %s: %s", path, e)


def _replace_with_retry(source: Path, destination: Path) -> None:
    """``os.replace`` を行い、``PermissionError`` は指数バックオフで再試行する。

    Raises:
        LibraryWriteBusyError: 再試行が有効な OS で ``REPLACE_MAX_ATTEMPTS`` 回とも
            ``PermissionError`` だった。
        OSError: それ以外の失敗 (再試行しない OS の ``PermissionError`` を含む)。
    """
    delay = REPLACE_INITIAL_BACKOFF_SECONDS
    for attempt in range(1, REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError as e:
            if not _RETRY_PERMISSION_ERRORS:
                raise
            if attempt == REPLACE_MAX_ATTEMPTS:
                raise LibraryWriteBusyError(
                    f"Cannot replace library file {str(destination)!r}: it is in use by "
                    f"another process (gave up after {REPLACE_MAX_ATTEMPTS} attempts): {e}"
                ) from e
            _logger.warning(
                "atomic write: %s is in use (attempt %d/%d), retrying in %.0f ms: %s",
                destination,
                attempt,
                REPLACE_MAX_ATTEMPTS,
                delay * 1000,
                e,
            )
            time.sleep(delay)
            delay *= REPLACE_BACKOFF_FACTOR


def _fsync_directory(directory: Path) -> None:
    """ディレクトリエントリの変更を永続化する (POSIX のみ、ベストエフォート)。"""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as e:
        _logger.debug("atomic write: cannot open directory %s for fsync: %s", directory, e)
        return
    try:
        os.fsync(fd)
    except OSError as e:
        _logger.debug("atomic write: directory fsync failed for %s: %s", directory, e)
    finally:
        os.close(fd)


def write_text_exclusive(path: str | Path, text: str) -> None:
    """``text`` を UTF-8 で ``path`` に**排他作成**で書き込む (ADR-0080 §A6-4)。

    既存ファイルを決して上書きしない (取り込みライブラリの保存用)。書き込みに失敗
    したら、作りかけのファイルを消してから失敗を伝える。

    Args:
        path: 書き込み先 (存在してはならない)。
        text: 書き込む内容。

    Raises:
        FileExistsError: ``path`` が既に存在する (呼び出し側が名前を変えて再試行する)。
        LibraryWriteError: それ以外の書き込み失敗。
    """
    target = Path(path)
    try:
        data = text.encode(_ENCODING)
        with open(target, "xb") as f:
            try:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            except OSError:
                f.close()
                _remove_quietly(target)
                raise
    except FileExistsError:
        raise
    except (OSError, UnicodeEncodeError) as e:
        raise LibraryWriteError(f"Cannot write library file {str(target)!r}: {e}") from e
    _fsync_directory(target.parent)


def move_to_backup(path: str | Path) -> Path:
    """``path`` を ``<name>.bak`` にリネームして退避する (ADR-0080 §A6-2)。

    既存の ``.bak`` は置き換える (1 世代)。``os.replace`` の再試行規則は
    :func:`atomic_write_text` と同じ。

    Args:
        path: 退避するファイル。

    Returns:
        退避先 (``<name>.bak``) の path。

    Raises:
        LibraryWriteBusyError: 他プロセスがファイルを開いていて、再試行しても
            リネームできなかった。
        LibraryWriteError: それ以外の失敗 (ファイル不在・権限不足など)。
    """
    source = Path(path)
    destination = backup_path_for(source)
    try:
        _replace_with_retry(source, destination)
    except LibraryWriteError:
        raise
    except OSError as e:
        raise LibraryWriteError(f"Cannot move library file {str(source)!r} aside: {e}") from e
    _fsync_directory(source.parent)
    return destination


def atomic_write_text(path: str | Path, text: str, *, backup: bool = True) -> None:
    """``text`` を UTF-8 で ``path`` にアトミックに書き込む (ADR-0080 §A6-1)。

    改行は変換しない (``"\\n"`` はどの OS でも ``"\\n"`` のまま書かれる)。
    書き込み先のディレクトリは作らない (呼び出し側の責務)。

    Args:
        path: 書き込み先。
        text: 書き込む内容。
        backup: ``True`` (既定) なら、既存ファイルの内容を ``<name>.bak`` に 1 世代
            退避してから置換する。

    Raises:
        LibraryWriteBusyError: 他プロセスがファイルを開いていて、再試行しても
            置換できなかった。書き込み先は変更されていない。
        LibraryWriteError: それ以外の書き込み失敗 (権限不足・ディスク不足・
            ディレクトリ不在など)。
    """
    target = Path(path)
    pending: list[Path] = []
    try:
        new_temp = _write_temp_file(target, text.encode(_ENCODING))
        pending.append(new_temp)
        if backup and target.is_file():
            backup_temp = _write_temp_file(backup_path_for(target), target.read_bytes())
            pending.append(backup_temp)
            _replace_with_retry(backup_temp, backup_path_for(target))
            pending.remove(backup_temp)
        _replace_with_retry(new_temp, target)
        pending.remove(new_temp)
    except LibraryWriteError:
        raise
    except (OSError, UnicodeEncodeError) as e:
        # UnicodeEncodeError: 孤立サロゲートなど UTF-8 に符号化できない文字を含む内容
        raise LibraryWriteError(f"Cannot write library file {str(target)!r}: {e}") from e
    finally:
        for leftover in pending:
            _remove_quietly(leftover)
    _fsync_directory(target.parent)
