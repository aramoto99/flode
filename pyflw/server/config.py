"""``pyflw-server`` 設定ファイル loader + Resolver (SPEC-0004)。

``~/.pyflw/config.toml`` の探索・パース・優先順位マージ・雛形生成を担う。
挙動は Jupyter Lab に合わせる:

- 設定ファイル不在: ``None`` を返す (呼び出し側は default で起動)
- TOML syntax error: :class:`PyflwError`
- 型違反 (例: ``port = "abc"``): :class:`PyflwError`
- 未知のキー / セクション: ``WARNING`` ログを出して継続

優先順位は ``CLI > 設定ファイル > default``。:class:`SettingsResolver` を
``CLI > env > file > default`` に拡張するときは ``__init__`` に ``env_config`` 引数を
追加するだけで済むよう、per-source dict を順序付きで持つ設計にしている (= 将来の
環境変数サポート用、SPEC §5)。

``Settings`` dataclass には ``host`` / ``port`` を足していない (= uvicorn 起動引数で
あり、``create_app`` に渡す内部設定とは分離した方が責務が明確なため)。本モジュール側で
別管理する。
"""

from __future__ import annotations

import dataclasses
import logging
import tomllib
from pathlib import Path
from typing import Any

from ..exceptions import PyflwError
from .settings import Settings

_logger = logging.getLogger("pyflw.server.config")

# ---------------------------------------------------------------------------
# 既知 schema (= warning 対象の判定に使う)
# ---------------------------------------------------------------------------

# ``Settings.workspace_root`` は TOML では ``workspace`` キーとして書く (= path 全体
# を root に統一するための alias)。それ以外のフィールド名は dataclass と TOML で同じ。
_WORKSPACE_TOML_KEY = "workspace"
_SETTINGS_FIELD_NAMES: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(Settings)
) - {"workspace_root"}

_KNOWN_SECTIONS = ("server", "settings")
_KNOWN_SERVER_KEYS: frozenset[str] = frozenset({"host", "port"})
# Settings dataclass の field 名 + workspace alias を許容する (二重管理を避けるため
# dataclass フィールドから動的生成、code-reviewer SHOULD 修正)。
_KNOWN_SETTINGS_KEYS: frozenset[str] = _SETTINGS_FIELD_NAMES | {_WORKSPACE_TOML_KEY}

# ---------------------------------------------------------------------------
# default 値 (= 設定ファイルにも CLI にも書かれなかった時の値)
# ``Settings`` dataclass の field default を Single Source of Truth として
# 参照すべきフィールドはここで再宣言しない。host/port は Settings に無いので
# ここで宣言する。
# ---------------------------------------------------------------------------

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8770


# ---------------------------------------------------------------------------
# Config path 探索
# ---------------------------------------------------------------------------


def _expand_home(path_str: str | Path) -> Path:
    """``~`` で始まる path を ``Path.home()`` で展開する。

    ``Path.expanduser()`` は ``os.environ['HOME']`` / ``USERPROFILE`` を直接参照する
    ため、テストで ``monkeypatch.setattr(Path, "home", ...)`` しても効かない。本関数
    は ``Path.home()`` 経由なので monkeypatch が効く。
    """
    s = str(path_str)
    if s == "~":
        return Path.home()
    if s.startswith("~/") or s.startswith("~\\"):
        return Path.home() / s[2:]
    return Path(s)


def resolve_config_path(*, explicit: Path | None) -> Path | None:
    """設定ファイルの実 path を返す。

    Args:
        explicit: ``--config=PATH`` で明示指定された path (``None`` なら暗黙探索)。

    Returns:
        - ``explicit`` が file として存在 → 解決済み絶対 path
        - ``explicit=None`` で ``~/.pyflw/config.toml`` が存在 → その path
        - ``explicit=None`` で暗黙 path も不在 → ``None`` (= 呼び出し側は default で起動)

    Raises:
        PyflwError: ``explicit`` 指定で path が存在しない / file ではない。
            暗黙探索の不在はエラーにせず ``None`` を返す (Jupyter Lab 準拠)。
    """
    if explicit is not None:
        p = _expand_home(explicit).resolve()
        if not p.exists():
            raise PyflwError(
                f"--config path does not exist: {p}. "
                f"Use 'pyflw-server --generate-config' to create a template."
            )
        if not p.is_file():
            raise PyflwError(f"--config path is not a file (directory?): {p}")
        return p
    default = default_user_config_path()
    if default.is_file():
        return default
    return None


def default_user_config_path() -> Path:
    """暗黙探索 path (``~/.pyflw/config.toml``) を返す。

    ``--generate-config`` の出力先としても使う。``Path.home()`` を経由するため、
    テストでは ``monkeypatch.setattr(Path, "home", ...)`` で隔離可能。
    """
    return Path.home() / ".pyflw" / "config.toml"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config_file(path: Path) -> dict[str, Any]:
    """TOML 設定ファイルを dict として読み込む。

    Args:
        path: 読み込み対象の TOML ファイル。

    Returns:
        パースされた dict。空ファイルなら空 dict。

    Raises:
        PyflwError: ファイル不在、ディレクトリ指定、TOML syntax error、
            読み取り権限なしのいずれか。
    """
    if not path.exists():
        raise PyflwError(f"Config file does not exist: {path}")
    if not path.is_file():
        raise PyflwError(f"Config path is not a file (directory?): {path}")
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise PyflwError(f"Failed to parse config at {path}: {e}") from e
    except PermissionError as e:
        raise PyflwError(f"Cannot read config (permission denied): {path}: {e}") from e


# ---------------------------------------------------------------------------
# SettingsResolver
# ---------------------------------------------------------------------------


class SettingsResolver:
    """CLI / 設定ファイル / default をマージして ``Settings`` と bind 情報を構築する。

    優先順位は ``CLI > file_config > default``。``cli`` dict は CLI argparse の
    Namespace から、ユーザーが明示指定したフィールドのみ ``None`` 以外の値で渡される
    想定 (``argparse.SUPPRESS`` で未指定属性を抑止する、または None を sentinel として
    扱う)。

    将来 env を ``CLI > env > file > default`` の順に挿入する際は ``__init__`` に
    ``env_config`` を追加し、内部の探索順を更新するだけで済む (SPEC §4)。
    """

    def __init__(
        self,
        *,
        cli: dict[str, Any],
        file_config: dict[str, Any],
    ) -> None:
        """Resolver を初期化する。

        Args:
            cli: CLI 引数の dict (``{"workspace": Path | None, "port": int | None,
                "host": str | None, ...}`` 等)。``None`` または欠如キーは「未指定」扱い。
            file_config: ``load_config_file`` が返した dict (``{"server": {...},
                "settings": {...}}``)。空 dict も可。
        """
        self._cli = cli
        self._file = file_config
        self._warn_unknown_sections_and_keys()

    # --- public API ----------------------------------------------------------

    def build_settings(self, *, default_workspace: Path) -> Settings:
        """``Settings`` インスタンスを構築する。

        Args:
            default_workspace: CLI / file のどちらにも ``workspace`` 指定がない時の
                fallback (= 通常 ``Path.cwd().resolve()``)。``Settings.workspace_root``
                は dataclass の default を持たないため、CLI 層から補完する必要がある。

        Returns:
            完全に構築された ``Settings``。

        Raises:
            PyflwError: 型違反、または workspace path が存在しない / file 指定など。
        """
        workspace = self._resolve_workspace(default_workspace=default_workspace)
        scope_batch_size = self._resolve_int_field(
            "scope_batch_size",
            section="settings",
            default=100,
        )
        max_concurrent = self._resolve_int_field(
            "max_concurrent",
            section="settings",
            default=4,
        )
        allow_origins = self._resolve_str_list_field(
            "allow_origins",
            section="settings",
            default=[],
        )
        library_paths_raw = self._resolve_str_list_field(
            "library_paths",
            section="settings",
            default=[],
        )
        library_paths = [_expand_home(p).resolve() for p in library_paths_raw]
        bundle_builtin = self._resolve_bool_field(
            "bundle_builtin_libraries",
            section="settings",
            default=True,
        )
        return Settings(
            workspace_root=workspace,
            scope_batch_size=scope_batch_size,
            max_concurrent=max_concurrent,
            allow_origins=allow_origins,
            library_paths=library_paths,
            bundle_builtin_libraries=bundle_builtin,
        )

    def build_server_bind(self) -> tuple[str, int]:
        """uvicorn 起動用の ``(host, port)`` を返す。

        Returns:
            ``(host, port)``。CLI > file > default の順で解決済み。

        Raises:
            PyflwError: 型違反 (port が int でない、host が str でない、空文字 host 等)。
        """
        host_raw = self._lookup("host", section="server")
        if host_raw is None:
            host: str = _DEFAULT_HOST
        else:
            if not isinstance(host_raw, str):
                raise PyflwError(
                    f"Invalid type for [server].host: expected str, "
                    f"got {type(host_raw).__name__}"
                )
            if not host_raw:
                raise PyflwError(
                    "Invalid value for [server].host: must be a non-empty string."
                )
            host = host_raw

        port_raw = self._lookup("port", section="server")
        if port_raw is None:
            port_value: int = _DEFAULT_PORT
        else:
            # bool は int のサブクラスなので明示的に弾く (port = true を許さない)
            if isinstance(port_raw, bool) or not isinstance(port_raw, int):
                raise PyflwError(
                    f"Invalid type for [server].port: expected int, "
                    f"got {type(port_raw).__name__}"
                )
            port_value = port_raw
        return host, port_value

    # --- internals -----------------------------------------------------------

    def _lookup(self, key: str, *, section: str) -> Any:
        """CLI > file の順で値を探す (``None`` は未指定扱い)。

        - CLI dict は flat (``{"host": ..., "port": ..., "workspace": ...}``)
        - file dict は section 付き (``{"server": {"host": ...}, "settings": {...}}``)
        """
        cli_val = self._cli.get(key)
        if cli_val is not None:
            return cli_val
        section_dict = self._file.get(section)
        if isinstance(section_dict, dict) and key in section_dict:
            return section_dict[key]
        return None

    def _resolve_workspace(self, *, default_workspace: Path) -> Path:
        raw = self._lookup("workspace", section="settings")
        if raw is None:
            return default_workspace
        if isinstance(raw, Path):
            ws = raw if not str(raw).startswith("~") else _expand_home(raw)
        elif isinstance(raw, str):
            ws = _expand_home(raw)
        else:
            raise PyflwError(
                f"Invalid type for [settings].workspace: expected str/Path, "
                f"got {type(raw).__name__}"
            )
        ws_resolved = ws.resolve()
        if not ws_resolved.exists():
            raise PyflwError(
                f"Workspace root does not exist: {ws_resolved}. "
                f"Create the directory first or specify a different workspace."
            )
        if not ws_resolved.is_dir():
            raise PyflwError(
                f"Workspace root is not a directory: {ws_resolved}. "
                f"workspace must point to a directory, not a file."
            )
        return ws_resolved

    def _resolve_int_field(self, key: str, *, section: str, default: int) -> int:
        raw = self._lookup(key, section=section)
        if raw is None:
            return default
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise PyflwError(
                f"Invalid type for [{section}].{key}: expected int, "
                f"got {type(raw).__name__}"
            )
        return raw

    def _resolve_bool_field(self, key: str, *, section: str, default: bool) -> bool:
        raw = self._lookup(key, section=section)
        if raw is None:
            return default
        if not isinstance(raw, bool):
            raise PyflwError(
                f"Invalid type for [{section}].{key}: expected bool, "
                f"got {type(raw).__name__}"
            )
        return raw

    def _resolve_str_list_field(
        self, key: str, *, section: str, default: list[str]
    ) -> list[str]:
        raw = self._lookup(key, section=section)
        if raw is None:
            return list(default)
        if not isinstance(raw, list):
            raise PyflwError(
                f"Invalid type for [{section}].{key}: expected list of str, "
                f"got {type(raw).__name__}"
            )
        result: list[str] = []
        for i, item in enumerate(raw):
            if not isinstance(item, str):
                raise PyflwError(
                    f"Invalid type for [{section}].{key}[{i}]: expected str, "
                    f"got {type(item).__name__}"
                )
            result.append(item)
        return result

    def _warn_unknown_sections_and_keys(self) -> None:
        """未知のセクション / キーに対して WARNING ログを出す (Jupyter lenient)。"""
        for section_name, section_value in self._file.items():
            if section_name not in _KNOWN_SECTIONS:
                _logger.warning(
                    "Unknown section [%s] in config file, ignored.",
                    section_name,
                )
                continue
            if not isinstance(section_value, dict):
                _logger.warning(
                    "Section [%s] is not a table (got %s), ignored.",
                    section_name,
                    type(section_value).__name__,
                )
                continue
            known = _KNOWN_SERVER_KEYS if section_name == "server" else _KNOWN_SETTINGS_KEYS
            for key in section_value:
                if key not in known:
                    _logger.warning(
                        "Unknown key '%s' in [%s], ignored.",
                        key,
                        section_name,
                    )


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

_TEMPLATE = """# ~/.pyflw/config.toml — pyflw-server configuration (SPEC-0004)
# Generated by `pyflw-server --generate-config`.
# Edit values below; uncomment lines to override defaults.
# Priority: CLI args > this file > defaults.

# === uvicorn server bind options ===
# These map to `uvicorn.run(host=..., port=...)` and control where the
# HTTP server listens.
[server]
host = "127.0.0.1"   # bind host (default: "127.0.0.1")
port = 8770          # bind port (default: 8770)

# === pyflw.server.Settings dataclass fields ===
# These are passed to `create_app(settings=Settings(...))`.
[settings]
# Workspace root for /api/v1/files/* (ADR-0041).
# Comment out to fall back to the current working directory at startup.
# workspace = "~/pyflw-workspace"

# WebSocket Scope batch size (default: 100, ADR-0011).
scope_batch_size = 100

# Max concurrent simulations (default: 4).
max_concurrent = 4

# CORS allowed origins (default: [] = CORS disabled).
# Opt in for frontend dev (e.g. Vite at http://localhost:5173).
allow_origins = []

# Library search paths for *.flwlib.json (ADR-0029).
# Files or directories; directories are scanned recursively.
library_paths = []

# Whether to auto-register the bundled std.flwlib.json (default: true, ADR-0029).
bundle_builtin_libraries = true
"""


def generate_config_template(path: Path, *, force: bool) -> None:
    """雛形 TOML を ``path`` に書き出す。

    Args:
        path: 出力先 (通常 ``~/.pyflw/config.toml``)。
        force: ``True`` で既存ファイルを上書き、``False`` で既存時は :class:`PyflwError`。

    Raises:
        PyflwError: ``force=False`` で既存ファイルあり。
    """
    if path.exists() and not force:
        raise PyflwError(
            f"Config file already exists: {path}. Use --force to overwrite."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE, encoding="utf-8")
    _logger.info("Wrote config template to %s", path)


__all__ = [
    "SettingsResolver",
    "default_user_config_path",
    "generate_config_template",
    "load_config_file",
    "resolve_config_path",
]
