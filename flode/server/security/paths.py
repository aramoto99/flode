"""Workspace path resolution with traversal defense (ADR-0041 §論点 2-A)。

REST ``/api/v1/files/*`` で利用者が渡す ``?path=...`` を **workspace root 配下**
に解決し、root 外への traversal や OS 固有の罠 (= Windows reserved name、
trailing space/dot、UNC、null byte) を一括検証する。

セキュリティ上の責務は本モジュールに集約する (= File API endpoint 各位置で
個別に検証しない、SSOT 原則)。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from ...exceptions import PathTraversalError

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f]")
"""null byte 含む ASCII control char (\\x00-\\x1f)。

path injection 防御のため、URL decode 後の文字列にこれが残っていれば拒否。
``\\t`` ``\\n`` ``\\r`` も含まれる (= path として正当な用途がない)。
"""

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:")
"""Windows ドライブ指定 (= ``C:`` や ``c:``) の検出。"""

_WIN_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(0, 10)),
        *(f"lpt{i}" for i in range(0, 10)),
    }
)
"""Windows 予約デバイス名 (case-insensitive で判定)。

Microsoft 公式仕様 (= "Naming a File"、CON / PRN / AUX / NUL / COM0-COM9 /
LPT0-LPT9) に準拠。Linux / macOS でも cross-platform portability を維持
するため拒否。``CON.flw.json`` のような拡張子付きも、basename 部分が
予約名なら全 OS で拒否される (= Windows ではこれらは reserved file として
アクセス不能)。``COM10`` 以降は予約名ではない。
"""


def resolve_workspace_path(workspace_root: Path, raw: str) -> Path:
    """``raw`` (URL encoded relative path) を ``workspace_root`` 配下に解決する。

    呼び出し側との契約:
        * ``raw`` は **単段 URL encoded** path を想定 (= REST query param
          ``?path=`` から取り出した文字列)。本関数で ``urllib.parse.unquote`` を
          1 回適用する。
        * **二重 encoded** (例: ``%252e%252e``) は意図的に decode せず、リテラル
          ``%2e`` として扱う (= reverse proxy 等で 2 段 decode される構成は
          File API 実装側の責務として扱わない)。
        * FastAPI ``Request.query_params["path"]`` は既に 1 段 decode 済の値を
          返すため、Starlette の挙動 (= ``%2F`` を ``/`` に展開する) と本関数の
          unquote が二重適用される懸念は **冪等の範囲内** (= リテラル ``%2F`` を
          含まない通常 path では影響なし)。File API 実装時にフレームワークの
          decode 挙動を確認すること。
        * 本関数は I/O を行わない (= TOCTOU race の対象外)。File API 側で
          ``resolve_workspace_path`` 通過後の path に対して ``open`` / ``stat``
          する間の symlink 差し替えは別途扱う。

    Args:
        workspace_root: ``--workspace=PATH`` で指定された絶対 path。本関数内部で
            ``resolve(strict=False)`` する。
        raw: 単段 URL encoded 相対 path (POSIX 形式、``/`` 区切り限定)。

    Returns:
        絶対 ``Path``。存在しない path も resolve 可能 (= ``strict=False``)。

    Raises:
        PathTraversalError: 以下のいずれか:
            * null byte / ASCII control char を含む
            * backslash (``\\``) を含む (POSIX 形式限定の API)
            * 絶対 path (``/`` 始まり) または Windows ドライブ (``C:`` 等)
            * 単体 ``..`` (= root の親に出る、resolve 前の fail-fast)
            * Windows 予約名 (CON / PRN / AUX / NUL / COM0-9 / LPT0-9、
              case-insensitive、拡張子付き含む)
            * 各セグメントが trailing space / dot で終わる (Windows トリミング
              挙動回避)
            * resolve 後 ``workspace_root`` 配下から外れる

            File API 側で 4xx response を返す際は **エラーメッセージに利用者の
            decoded 入力を含めない** こと (log injection / 情報漏洩の多層防御)。
    """
    decoded = unquote(raw)

    # Step 1: null byte / control char 拒否
    # backslash 検査より先に置く理由 — control char は injection の最も危険な
    # ベクタで、後続のメッセージや FS 操作に到達する前に最初に弾く。
    if _CONTROL_CHAR_RE.search(decoded):
        raise PathTraversalError("Path contains control characters or null byte")

    # Step 2: backslash 拒否 (POSIX path 形式限定の API)
    # UNC ``\\server\share`` や Windows-style ``\Windows\System32`` を同時に弾く。
    if "\\" in decoded:
        raise PathTraversalError("Backslash not allowed in workspace path; use forward slash")

    # Step 3: 絶対 path / Windows ドライブ拒否
    if decoded.startswith("/"):
        raise PathTraversalError("Absolute path not allowed")
    if _WIN_DRIVE_RE.match(decoded):
        raise PathTraversalError("Drive-qualified path not allowed")

    # Step 4: 単体 ``..`` の fail-fast 拒否
    # 安全性は Step 6/7 (resolve + containment check) で十分担保されているが、
    # ``raw == ".."`` の典型ケースで早期に明確なエラーメッセージを返すための
    # 保険。``.strip()`` で先頭/末尾の whitespace のみ除去 (= ``"  ..  "`` も
    # ここで拾う)。``foo/..`` のような compound は Step 6/7 で扱う。
    if decoded.strip() == "..":
        raise PathTraversalError("Parent escape not allowed")

    # Step 5: 各セグメント検証 (Windows 予約名 + trailing space/dot)
    # ``.`` ``..`` ``""`` セグメントは通常 path 構成要素なので skip、resolve +
    # containment check で扱う。
    for seg in decoded.split("/"):
        if seg in ("", ".", ".."):
            continue
        if seg.endswith((" ", ".")):
            raise PathTraversalError(f"Path segment with trailing space or dot: {seg!r}")
        # 拡張子前の base 部分のみで予約名判定 (= ``CON.flw.json`` も拒否)。
        base = seg.split(".", 1)[0].lower()
        if base in _WIN_RESERVED_NAMES:
            raise PathTraversalError(f"Windows reserved name: {seg!r}")

    # Step 6: resolve under workspace_root
    # ``strict=False`` で存在しない path も resolve、symlink は辿る。
    root_resolved = workspace_root.resolve(strict=False)
    candidate = (root_resolved / decoded).resolve(strict=False)

    # Step 7: containment check
    # symlink 経由での root 外脱出はここで弾かれる (resolve が symlink を辿るため)。
    try:
        candidate.relative_to(root_resolved)
    except ValueError as e:
        raise PathTraversalError(f"Path escapes workspace root: {decoded!r}") from e

    return candidate
