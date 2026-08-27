"""ブラウザ由来の cross-site 書き込み要求 (CSRF) を拒否する request guard (SPEC-0023 追補)。

背景 (security-reviewer 指摘、v0.49.0): flode は loopback bind を「ローカルの信頼できる
利用者しか到達しない」前提で無認証だが、**ブラウザ** はその前提の外にいる。利用者が
任意のサイトを閲覧しているだけで、そのページの JS は
``fetch("http://127.0.0.1:8770/api/v1/simulations", {method: "POST", mode: "no-cors",
headers: {"Content-Type": "text/plain"}, body: ...})`` (= preflight の要らない
*simple request*) を送れる。``PythonFunction`` 導入後はこれが任意コード実行に直結する。

防御 (state-changing = ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` にのみ適用):

1. **Content-Type 強制**: 本文を持つ要求は ``application/json`` 以外を 415 で拒否する。
   これで simple request が成立しなくなり、cross-origin 送信には preflight が必須になる
   (CORS ミドルウェアが ``allow_origins`` 未設定なら preflight は失敗する)
2. **Origin 検証**: ``Origin`` ヘッダがある要求は、(a) ``settings.allow_origins`` に
   含まれる、または (b) 要求の ``Host`` と同一オリジンで **かつ** そのホストが IP
   リテラル / ``localhost`` (= DNS rebinding で偽装できない名前) のときだけ通す。
   ``Origin: null`` (sandbox iframe / file://) は拒否。``Origin`` が無い要求
   (= curl 等の非ブラウザクライアント) はそのまま通す — ブラウザは書き込み要求に
   必ず ``Origin`` を付けるので、無いものはブラウザ由来ではない

ホスト名 (``http://mypc.local:8770`` 等) で自サーバーにアクセスする運用は
``--allow-origin http://mypc.local:8770`` で明示的に許可する。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

STATE_CHANGING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})
JSON_MEDIA_TYPE = "application/json"


@dataclass(frozen=True)
class RequestRejection:
    """guard が要求を拒否する理由 (HTTP status + 人間可読メッセージ)。"""

    status_code: int
    detail: str


def _hostname_of(host_with_port: str) -> str:
    """``Host`` / origin の ``host[:port]`` からホスト名部分 (小文字、``[]`` 除去) を返す。"""
    h = host_with_port.strip().lower()
    if h.startswith("["):
        end = h.find("]")
        return h[1:end] if end > 0 else h
    if h.count(":") == 1:
        return h.rsplit(":", 1)[0]
    return h


def is_unspoofable_host(hostname: str) -> bool:
    """DNS rebinding で偽装できないホスト名か (= IP リテラルまたは ``localhost``)。"""
    name = hostname.strip().lower().strip("[]")
    if name == "localhost":
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _media_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def check_state_changing_request(
    *,
    method: str,
    origin: str | None,
    host: str | None,
    content_type: str | None,
    has_body: bool,
    allow_origins: list[str] | tuple[str, ...],
) -> RequestRejection | None:
    """書き込み要求を通してよいか判定する純粋関数。``None`` = 許可。

    Args:
        method: HTTP メソッド。
        origin: ``Origin`` ヘッダ (無ければ ``None``)。
        host: ``Host`` ヘッダ (無ければ ``None``)。
        content_type: ``Content-Type`` ヘッダ。
        has_body: 本文があるか (``Content-Length > 0`` または ``Transfer-Encoding`` あり)。
        allow_origins: ``settings.allow_origins`` (CORS 許可オリジンと共用)。
    """
    if method.upper() not in STATE_CHANGING_METHODS:
        return None
    if has_body and _media_type(content_type) != JSON_MEDIA_TYPE:
        return RequestRejection(
            415,
            f"State-changing requests must use Content-Type: {JSON_MEDIA_TYPE} "
            f"(got {content_type!r}). This blocks cross-site form/simple requests.",
        )
    if origin is None:
        return None
    origin_norm = origin.strip().lower()
    if origin_norm in {o.strip().lower().rstrip("/") for o in allow_origins}:
        return None
    if origin_norm == "null":
        return RequestRejection(403, "Requests from an opaque (null) origin are rejected.")
    parts = urlsplit(origin_norm)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return RequestRejection(403, f"Malformed Origin header: {origin!r}.")
    if host is not None and parts.netloc == host.strip().lower():
        if is_unspoofable_host(_hostname_of(parts.netloc)):
            return None
        return RequestRejection(
            403,
            f"Same-origin request via hostname {parts.netloc!r} is rejected to prevent DNS "
            f"rebinding; add it explicitly with --allow-origin {origin}.",
        )
    return RequestRejection(
        403,
        f"Cross-origin request from {origin!r} is rejected. Add it with --allow-origin "
        f"if this is your own frontend.",
    )
