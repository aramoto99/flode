"""``resolve_workspace_path`` の Path traversal セキュリティテスト (ADR-0041 §論点 2-A)。

各拒否カテゴリの境界条件と正常系を網羅する。Symlink で root 外を指すケースは
POSIX のみ実機テスト (Windows は ``mklink`` が admin 権限要のため skip)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from flode.exceptions import PathTraversalError
from flode.server.security import resolve_workspace_path

# ---------------------------------------------------------------------------
# 拒否系
# ---------------------------------------------------------------------------


class TestRejectAbsoluteAndDriveAndUNC:
    """絶対 path / Windows ドライブ / UNC を全て拒否。"""

    def test_posix_absolute_root(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "/etc/passwd")

    def test_posix_absolute_inside_workspace_string(self, tmp_path: Path) -> None:
        # 文字列上「/」始まりは workspace 配下文字列でも絶対 path 扱い
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "/foo.flw.json")

    def test_windows_backslash_absolute(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "\\Windows\\System32")

    def test_windows_drive_letter(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "C:/Windows/System32")

    def test_windows_drive_letter_lowercase(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "c:/foo")

    def test_unc_path(self, tmp_path: Path) -> None:
        # ``\\server\share`` (UNC) — backslash 拒否で同時にカバー
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "\\\\server\\share")


class TestRejectBackslash:
    """API は POSIX path 限定。backslash は全位置で拒否。"""

    def test_backslash_in_middle(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "subdir\\foo.flw.json")

    def test_single_backslash(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "\\")


class TestRejectParentEscape:
    """単体 ``..`` および resolve 後 root 外を指す path を拒否。"""

    def test_pure_parent(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "..")

    def test_parent_with_whitespace(self, tmp_path: Path) -> None:
        # strip 後に ``..`` 単体になるケース
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "  ..  ")

    def test_parent_with_subdir_escapes(self, tmp_path: Path) -> None:
        # ``../foo`` は root の親に行く → containment check で拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "../foo")

    def test_compound_escape(self, tmp_path: Path) -> None:
        # ``foo/../../etc`` は root 上に出る → 拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo/../../etc")

    def test_url_encoded_parent(self, tmp_path: Path) -> None:
        # URL encoded ``%2e%2e`` は unquote 後 ``..`` → 拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "%2e%2e/etc")

    def test_url_encoded_parent_double(self, tmp_path: Path) -> None:
        # ``%2e%2e%2f%2e%2e%2fetc`` → ``../../etc`` → 拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "%2e%2e%2f%2e%2e%2fetc")


class TestRejectControlChars:
    """null byte / control char を拒否 (path injection 防御)。"""

    def test_null_byte(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo\x00.txt")

    def test_control_char_soh(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo\x01bar.txt")

    def test_control_char_tab(self, tmp_path: Path) -> None:
        # \t (= \x09) も control char として拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo\tbar.txt")

    def test_control_char_newline(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo\nbar.txt")

    def test_url_encoded_null_byte(self, tmp_path: Path) -> None:
        # ``%00`` は unquote 後 null byte → 拒否
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo%00.txt")


class TestRejectWindowsReservedNames:
    """Windows 予約名 (CON, PRN, AUX, NUL, COM1-9, LPT1-9) を全 OS で拒否。

    cross-platform で portability を確保するため、POSIX 上でも拒否する。
    """

    @pytest.mark.parametrize(
        "name",
        [
            "CON.flw.json",
            "PRN.txt",
            "AUX.json",
            "NUL.flw.json",
            "COM0.flw.json",
            "COM1.flw.json",
            "COM9.flw.json",
            "LPT0.flw.json",
            "LPT1.flw.json",
            "LPT9.flw.json",
        ],
    )
    def test_reserved_with_extension(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, name)

    @pytest.mark.parametrize("name", ["con", "prn", "aux", "nul", "com0", "com1", "lpt0", "lpt1"])
    def test_reserved_without_extension(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, name)

    @pytest.mark.parametrize("name", ["Con", "PrN", "AuX", "nUl"])
    def test_reserved_mixed_case(self, tmp_path: Path, name: str) -> None:
        # case-insensitive 比較
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, name)

    def test_reserved_in_subdirectory(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "controllers/CON.flw.json")

    def test_reserved_as_directory_name(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "CON/foo.flw.json")

    def test_non_reserved_with_similar_prefix(self, tmp_path: Path) -> None:
        # ``CONS`` や ``CONFIG`` は予約名ではない (= ``CON`` の prefix だが別名)
        result = resolve_workspace_path(tmp_path, "CONFIG.flw.json")
        assert result.name == "CONFIG.flw.json"

    def test_non_reserved_com10(self, tmp_path: Path) -> None:
        # ``COM10`` は Windows 予約名ではない (= COM1-9 のみ)
        result = resolve_workspace_path(tmp_path, "COM10.flw.json")
        assert result.name == "COM10.flw.json"


class TestRejectTrailingSpaceAndDot:
    """Windows の trailing space / dot 暗黙トリミング挙動を回避するため拒否。"""

    def test_trailing_space(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo.txt ")

    def test_trailing_dot_after_extension(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo.txt.")

    def test_trailing_dot_no_extension(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo.")

    def test_trailing_space_in_directory_segment(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo /bar.txt")

    def test_trailing_dot_in_directory_segment(self, tmp_path: Path) -> None:
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(tmp_path, "foo./bar.txt")


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------


class TestAllowSimplePaths:
    """シンプルなファイル / ディレクトリ path を許容。"""

    def test_simple_file(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "pid.flw.json")
        assert result == (tmp_path.resolve() / "pid.flw.json")

    def test_nested_file(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "controllers/pid.flw.json")
        assert result == (tmp_path.resolve() / "controllers" / "pid.flw.json")

    def test_directory_with_trailing_slash(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "controllers/")
        assert result == (tmp_path.resolve() / "controllers")

    def test_dot_resolves_to_root(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, ".")
        assert result == tmp_path.resolve()

    def test_empty_string_resolves_to_root(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "")
        assert result == tmp_path.resolve()

    def test_deep_nesting(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "a/b/c/d/e.flw.json")
        assert result == (tmp_path.resolve() / "a" / "b" / "c" / "d" / "e.flw.json")


class TestAllowComplexPaths:
    """resolve 後に root 内に収まるなら ``..`` を含む compound path も許容。"""

    def test_dotdot_in_middle_resolves_inside(self, tmp_path: Path) -> None:
        # ``foo/../bar`` → ``bar`` (root 内) → 許容
        result = resolve_workspace_path(tmp_path, "foo/../bar")
        assert result == (tmp_path.resolve() / "bar")

    def test_multiple_dots_resolves_inside(self, tmp_path: Path) -> None:
        # ``a/b/../c`` → ``a/c``
        result = resolve_workspace_path(tmp_path, "a/b/../c")
        assert result == (tmp_path.resolve() / "a" / "c")


class TestAllowUrlEncoding:
    """URL encoded segment を unquote してから検証。"""

    def test_url_encoded_dot(self, tmp_path: Path) -> None:
        # ``%2E`` は ``.`` の URL encoding (= ``pid.flw.json`` を encode したもの)
        result = resolve_workspace_path(tmp_path, "controllers/pid%2Eflw.json")
        assert result == (tmp_path.resolve() / "controllers" / "pid.flw.json")

    def test_url_encoded_slash_in_filename(self, tmp_path: Path) -> None:
        # URL encoded ``%2F`` は通常の ``/`` として扱われる (unquote)、
        # subpath 区切り扱い
        result = resolve_workspace_path(tmp_path, "controllers%2Fpid.flw.json")
        assert result == (tmp_path.resolve() / "controllers" / "pid.flw.json")

    def test_url_encoded_unicode(self, tmp_path: Path) -> None:
        # ``コント`` の URL encoding (utf-8 = 9 bytes / 3 chars)
        result = resolve_workspace_path(tmp_path, "%E3%82%B3%E3%83%B3%E3%83%88.flw.json")
        assert result == (tmp_path.resolve() / "コント.flw.json")


class TestAllowUnicode:
    """非 ASCII ファイル名を許容 (= modern FS 対応)。"""

    def test_japanese_filename(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "コントローラ.flw.json")
        assert result == (tmp_path.resolve() / "コントローラ.flw.json")

    def test_japanese_directory(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "日本語/foo.flw.json")
        assert result == (tmp_path.resolve() / "日本語" / "foo.flw.json")

    def test_emoji_filename(self, tmp_path: Path) -> None:
        # 絵文字も valid (= モダン FS 対応)
        result = resolve_workspace_path(tmp_path, "🚀.flw.json")
        assert result == (tmp_path.resolve() / "🚀.flw.json")


# ---------------------------------------------------------------------------
# Symlink 系 (POSIX のみ)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows の mklink は admin 権限を要するため CI/local で skip",
)
class TestSymlinkBoundaries:
    """workspace root 内 symlink が root 外を指すケースを拒否。"""

    def test_symlink_pointing_outside_root_is_rejected(self, tmp_path: Path) -> None:
        """root 内 symlink ``link`` → root 外 dir。``link/foo.txt`` を解決すると
        symlink を辿って root 外に出る → containment check で拒否。
        """
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        root = tmp_path / "ws"
        root.mkdir()
        link = root / "link"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(PathTraversalError):
            resolve_workspace_path(root, "link/foo.txt")

    def test_symlink_pointing_inside_root_is_allowed(self, tmp_path: Path) -> None:
        """root 内 symlink → root 内別 dir は許容。"""
        root = tmp_path / "ws"
        root.mkdir()
        target = root / "real"
        target.mkdir()
        link = root / "alias"
        link.symlink_to(target, target_is_directory=True)
        # ``alias/foo.txt`` を解決 → ``real/foo.txt`` (root 内) → 許容
        result = resolve_workspace_path(root, "alias/foo.txt")
        # resolve は symlink を辿るので alias → real に変換される
        assert result == (target.resolve() / "foo.txt")


# ---------------------------------------------------------------------------
# 返り値型の確認
# ---------------------------------------------------------------------------


class TestReturnValue:
    """返り値が absolute Path であること、存在しなくても resolve 可能なこと。"""

    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        result = resolve_workspace_path(tmp_path, "subdir/file.flw.json")
        assert result.is_absolute()

    def test_works_for_nonexistent_path(self, tmp_path: Path) -> None:
        # ``strict=False`` で存在しない path も resolve 可能
        result = resolve_workspace_path(tmp_path, "does-not-exist/yet.flw.json")
        assert result == (tmp_path.resolve() / "does-not-exist" / "yet.flw.json")
