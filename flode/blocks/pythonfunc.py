"""SPEC-0023 / ADR-0073: ``PythonFunction`` ブロック (俗称 p-function)。

ユーザーが書いた ``@block`` 形の Python ソース (モデル JSON にインライン保存) を
実行するブロック。既存の :class:`~flode.blocks.userfunc.Fcn` (式サンドボックス) で
書けない **状態あり / MIMO / 任意 import** のロジックを GUI から書くための入口。

脅威モデル (SPEC-0023 §機能要件 5 / ADR-0073 §論点 3, 4)
=====================================================

本ブロックは **意図的にサンドボックスしない**。``PythonFunction`` を含むモデルを
実行することは、その中の Python コードを **自分の権限で実行すること** と同義である。
「まず :class:`Fcn` を検討し、式で書けない時だけ本ブロックを使う」のが選択指針。

そのうえで、実行を **1 点** に集約し、その手前に 2 つの門を置く:

* **exec の実行点は** :meth:`PythonFunction._build` **だけ**。``__init__`` は
  ``compile()`` + 静的解析 (:mod:`flode.blocks.pythonfunc_source`) のみで、
  **モデルを開いただけではユーザーコードは 1 行も実行されない**
* **hard gate** (:func:`set_python_block_policy`、セキュリティ機構): プロセス全体の
  許可フラグ。サーバは非 loopback bind で明示フラグが無い限り ``allowed=False`` に
  設定する。REST / WS / CLI / Python API のどの経路でも ``_build()`` で同じ判定を通る
* **soft gate** (:func:`compute_python_digest`、UX 機構): 「このモデルは Python を
  実行する」の告知と同意をサーバの start API が要求する。REST を直接叩けば
  bypass できるが、それは欠陥ではなく定義である (ADR-0073 §論点 4)

``exec`` 名前空間には ``block`` / ``np`` / ``npt`` を注入し、``__builtins__`` は制限
しない (部分制限は「安全でないのに安全に見える」最悪状態を作る)。
"""

from __future__ import annotations

import builtins
import hashlib
import linecache
import logging
import traceback
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.decorator import block
from ..core.identifiers import normalize_block_id
from ..exceptions import (
    BlockSpecError,
    FlodeError,
    PythonBlocksDisabledError,
    PythonFunctionEvalError,
)
from .pythonfunc_source import (
    GENERATED_MODULE_NAME,
    SourceSpec,
    analyze_source,
    source_filename,
)

if TYPE_CHECKING:  # pragma: no cover - 循環 import 回避
    from ..core.simulator import Simulator

_logger = logging.getLogger("flode.blocks.pythonfunc")

#: パレットからドロップした直後の既定ソース (1 入力 1 出力、ゲイン)。
DEFAULT_CODE = (
    "@block\n"
    "def my_function(t: float, u: float, *, gain: float = 1.0) -> float:\n"
    '    """1 入力 1 出力。u に gain を掛けて返す。"""\n'
    "    return gain * u\n"
)


# ---------------------------------------------------------------------------
# hard gate: プロセス全体の実行 policy (ADR-0073 §論点 4 (H))
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonBlockPolicy:
    """``PythonFunction`` の ``exec`` 可否 (プロセス全体)。

    Attributes:
        allowed: ``False`` なら ``_build()`` が :class:`PythonBlocksDisabledError` を投げる。
        reason: 拒否理由 (エラーメッセージに埋め込む)。
    """

    allowed: bool = True
    reason: str = ""


_policy = PythonBlockPolicy()


def set_python_block_policy(*, allowed: bool, reason: str = "") -> None:
    """``PythonFunction`` の実行可否をプロセス全体で設定する。

    サーバ (``flode`` CLI) は bind アドレスとフラグから決めた policy をここに流し込む。
    Python API から直接使う場合の既定は **許可** (SPEC-0023 §5)。埋め込み利用者が
    自前で禁止したい場合にも同じ API を使う (= 機構を 2 つ作らない)。

    Args:
        allowed: 実行を許可するか。
        reason: 拒否時にエラーメッセージへ添える理由。
    """
    global _policy
    _policy = PythonBlockPolicy(allowed=allowed, reason=reason)
    _logger.info("PythonFunction policy: allowed=%s reason=%r", allowed, reason)


def get_python_block_policy() -> PythonBlockPolicy:
    """現在の policy を返す。"""
    return _policy


def _require_execution_allowed(block_id: str | None) -> None:
    if _policy.allowed:
        return
    reason = f" ({_policy.reason})" if _policy.reason else ""
    raise PythonBlocksDisabledError(
        f"PythonFunction[{block_id}]: execution of Python blocks is disabled in this "
        f"process{reason}. Start the server with --allow-python-blocks or set "
        f"[server] allow_python_blocks = true in the config file to enable it "
        f"(this exposes remote code execution to anyone who can reach the server).",
        block_id=block_id,
    )


# ---------------------------------------------------------------------------
# exec ローダ (唯一の実行点、ADR-0073 §論点 3)
# ---------------------------------------------------------------------------


def _exec_namespace() -> dict[str, Any]:
    return {
        "__builtins__": builtins.__dict__,
        "__name__": GENERATED_MODULE_NAME,
        "block": block,
        "np": np,
        "npt": npt,
    }


def exec_block_source(
    code: str, *, block_id: str | None, filename: str | None = None
) -> tuple[type[Block], dict[str, Any]]:
    """``PythonFunction`` の唯一の ``exec`` 実行点。冒頭で hard gate を必ず通る。

    ``linecache`` にソースを登録してから ``exec`` するため、ユーザーコード内の例外
    traceback に該当行のテキストが載る。``__builtins__`` は制限しない (= ユーザーコードが
    ``builtins`` を書き換えればプロセス全体に及ぶ。``import builtins`` と等価で、
    サンドボックスしない設計上の既知の性質)。

    Args:
        code: ユーザーソース。
        block_id: エラーメッセージ用のブロック ID。
        filename: ``compile`` / ``linecache`` に使う擬似ファイル名。省略時は
            ``<pythonfunction:{block_id}>``。インスタンスごとに一意な名前を渡すと、
            同 id のブロックが共存しても traceback のソース行が混ざらない。

    Returns:
        ``(生成 Block サブクラス, exec 名前空間)``。名前空間は生成関数の
        ``__globals__`` が参照し続けるので、呼び出し側が寿命を管理する。

    Raises:
        PythonBlocksDisabledError: プロセス policy が実行を禁止している。
        BlockSpecError: 名前空間に ``@block`` 生成 class がちょうど 1 個見つからない。
        Exception: ユーザーコードの module レベル文が投げた例外はそのまま伝播する
            (呼び出し側 :meth:`PythonFunction._build` が包み直す)。
    """
    # 呼び出し側の規約に依存せず、この関数自体が gate を通る (不変条件 (a) を構造で担保)。
    _require_execution_allowed(block_id)
    filename = filename if filename is not None else source_filename(block_id)
    linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)
    ns = _exec_namespace()
    compiled = compile(code, filename, "exec")
    exec(compiled, ns)  # noqa: S102 - SPEC-0023: サンドボックスしない設計 (hard gate 通過後)
    generated = [
        v
        for v in ns.values()
        if isinstance(v, type)
        and issubclass(v, Block)
        and hasattr(v, "_flode_structure")
        and getattr(v, "__module__", None) == GENERATED_MODULE_NAME
    ]
    if len(generated) != 1:
        raise BlockSpecError(
            f"PythonFunction[{block_id}]: expected exactly one @block-generated class "
            f"after executing the source, found {len(generated)}.",
            block_id=block_id,
        )
    return generated[0], ns


# ---------------------------------------------------------------------------
# soft gate: 承認 digest (ADR-0073 §論点 4 (S))
# ---------------------------------------------------------------------------


def iter_python_functions(
    blocks: Sequence[Block], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[str, PythonFunction]]:
    """``blocks`` (Subsystem 内部を再帰) から ``PythonFunction`` を ``(qualified_id, block)`` で列挙する。

    ``qualified_id`` は ``"outer_sub/inner_sub/pf_1"`` 形式。
    """
    for b in blocks:
        bid = b.id if b.id is not None else ""
        if isinstance(b, PythonFunction):
            yield "/".join((*prefix, bid)), b
        inner = getattr(b, "_inner_blocks", None)
        if inner:
            yield from iter_python_functions(inner, (*prefix, bid))


def compute_python_digest(simulator: Simulator) -> str | None:
    """モデル内の全 ``PythonFunction`` のコードから承認 digest (SHA-256 hex) を計算する。

    ``(qualified_id, code)`` を **id でソート** して連結するので、JSON 内のブロック
    並び順に依存しない。``PythonFunction`` を含まないモデルでは ``None``。
    コードを 1 文字でも変えれば digest が変わる (= 承認が自動失効する)。
    """
    items = sorted((qid, pf.code) for qid, pf in iter_python_functions(simulator.blocks))
    if not items:
        return None
    canon = "\n".join(f"{qid}\x00{code}" for qid, code in items)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ユーザーコード例外の包み直し (ADR-0073 §論点 6)
# ---------------------------------------------------------------------------


def _user_frame_info(exc: BaseException, *, filename: str) -> tuple[int | None, str | None, str]:
    """ユーザーコードのフレームだけから ``(lineno, source_line, user_traceback)`` を抽出する。"""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename]
    last = frames[-1] if frames else None
    lineno = last.lineno if last is not None else None
    source_line = (last.line or None) if last is not None else None
    user_tb = "".join(traceback.format_list(frames)) if frames else ""
    user_tb += f"{type(exc).__name__}: {exc}"
    return lineno, source_line, user_tb


def _wrap_user_exception(
    exc: BaseException, *, filename: str, block_id: str | None
) -> PythonFunctionEvalError:
    """実行時 (``output`` / ``derivative`` / ``update`` / ``reset``) のユーザー例外を包む。"""
    lineno, source_line, user_tb = _user_frame_info(exc, filename=filename)
    where = f" (line {lineno})" if lineno is not None else ""
    return PythonFunctionEvalError(
        f"PythonFunction[{block_id}]: {type(exc).__name__}: {exc}{where}",
        lineno=lineno,
        source_line=source_line,
        user_traceback=user_tb,
        block_id=block_id,
    )


def _wrap_exec_exception(
    exc: BaseException, *, filename: str, block_id: str | None
) -> BlockSpecError:
    """``exec`` 中 (= module レベル文 / import 失敗) の例外を ``BlockSpecError`` に包む。

    SPEC-0023 §機能要件 6: モデルの構成が壊れている扱い (= ``start_validation``)。
    実行時の値依存の例外 (``PythonFunctionEvalError``) とは区別する。
    """
    lineno, _source_line, _tb = _user_frame_info(exc, filename=filename)
    where = f" (line {lineno})" if lineno is not None else ""
    return BlockSpecError(
        f"PythonFunction[{block_id}]: module-level code failed during exec: "
        f"{type(exc).__name__}: {exc}{where}",
        block_id=block_id,
    )


def _verify_structure(cls: type[Block], spec: SourceSpec, block_id: str | None) -> None:
    """静的解析結果と ``exec`` 後の生成 class の構造が一致することを確認する。"""
    s = cls._flode_structure  # type: ignore[attr-defined]
    expected = (
        spec.n_inputs,
        spec.n_outputs,
        spec.n_states,
        spec.direct_feedthrough,
        spec.sample_time,
    )
    actual = (s.n_inputs, s.n_outputs, s.n_states, s.direct_feedthrough, s.sample_time)
    if expected != actual:
        raise BlockSpecError(
            f"PythonFunction[{block_id}]: block structure after execution "
            f"(inputs, outputs, states, direct_feedthrough, sample_time)={actual} differs "
            f"from the static analysis {expected}. The @block arguments and annotations "
            f"must be literal so that both agree.",
            block_id=block_id,
        )


# ---------------------------------------------------------------------------
# Block 本体
# ---------------------------------------------------------------------------


class PythonFunction(Block):
    """ユーザーが書いた ``@block`` 形の Python ソースを実行するブロック (SPEC-0023)。

    **セキュリティ**: 本ブロックはサンドボックスされない。このブロックを含むモデルを
    実行することは、その中の Python コードを自分の権限で実行することと同義である。
    式で書けるロジックには :class:`~flode.blocks.userfunc.Fcn` を使うこと。

    構造 (ポート数 / 状態数 / 直達 / sample_time / パラメータ宣言) は **コードが
    SSOT** で、``__init__`` が静的解析で確定する (``exec`` はしない)。ユーザーコードの
    実行は :meth:`_build` (= ``Simulator.run()`` の構造解析直前) で 1 回だけ起きる。

    Args:
        code: ``@block`` 形の関数定義を 1 つ含む Python ソース。
        user_params: コードの keyword-only 引数に対応する値 (``{"gain": 2.0}`` 等)。
            宣言されていないキーは警告して無視する。
        id: ブロック ID。
        name: ``id`` の別名 (Phase 0 互換)。

    Raises:
        PythonFunctionSourceError: ``code`` が構文エラー、または静的解析で受理できない
            (``BlockSpecError`` のサブクラス)。

    Example:
        >>> from flode.blocks import PythonFunction
        >>> pf = PythonFunction(code=DEFAULT_CODE, user_params={"gain": 3.0})
        >>> (pf.n_inputs, pf.n_outputs, pf.n_states)
        (1, 1, 0)
    """

    def __init__(
        self,
        code: str = DEFAULT_CODE,
        user_params: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        # ADR-0071 §(3): Block.__init__ が行う NFC 正規化を先出しし、静的解析の
        # エラーメッセージ / 擬似ファイル名にも正規化済み id を使う (= _build 時と一致)。
        raw_id = id if id is not None else name
        norm_id = normalize_block_id(raw_id) if isinstance(raw_id, str) else raw_id
        spec = analyze_source(code, block_id=norm_id)
        super().__init__(
            id=id,
            name=name,
            n_inputs=spec.n_inputs,
            n_outputs=spec.n_outputs,
            n_states=spec.n_states,
            direct_feedthrough=spec.direct_feedthrough,
            sample_time=spec.sample_time,
        )
        self.code: str = code
        self._static_spec: SourceSpec = spec
        self.user_params: dict[str, Any] = self._filter_user_params(user_params, spec)
        self._inner: Block | None = None
        self._exec_ns: dict[str, Any] | None = None
        # 擬似ファイル名はインスタンスごとに一意にする (同 id のブロックが top-level と
        # Subsystem 内部で共存しても linecache / traceback のソース行が混ざらない)。
        self._source_filename: str = f"{source_filename(self.id)[:-1]}#{uuid.uuid4().hex[:8]}>"
        self._params = {"code": code, "user_params": dict(self.user_params)}

    @property
    def spec(self) -> SourceSpec:
        """静的解析で確定した構造 (read-only)。"""
        return self._static_spec

    def _filter_user_params(
        self, user_params: dict[str, Any] | None, spec: SourceSpec
    ) -> dict[str, Any]:
        if user_params is None:
            return {}
        if not isinstance(user_params, dict):
            raise BlockSpecError(
                f"PythonFunction[{self.id}]: user_params must be a dict, "
                f"got {type(user_params).__name__}",
                block_id=self.id,
            )
        declared = {p[0] for p in spec.params_spec}
        kept: dict[str, Any] = {}
        for key, value in user_params.items():
            if key in declared:
                kept[key] = value
            else:
                _logger.warning(
                    "PythonFunction[%s]: user_params key %r is not declared by %s(); ignored",
                    self.id,
                    key,
                    spec.func_name,
                )
        return kept

    # ---- 構造解析 hook (Simulator._execution_order の直前に呼ばれる) ----

    def _build(self) -> None:
        """hard gate → ``exec`` → 構造突合 → 内包インスタンス生成 → ``x0`` 確定。

        ``exec`` はインスタンスあたり 1 回だけ (同一 ``Simulator`` を複数回 ``run()``
        しても module レベルの state は再初期化されない。開き直せばクリーンになる)。
        """
        if self._inner is None:
            _require_execution_allowed(self.id)
            filename = self._source_filename
            try:
                cls, ns = exec_block_source(self.code, block_id=self.id, filename=filename)
            except FlodeError:
                linecache.cache.pop(filename, None)
                raise
            except Exception as exc:  # noqa: BLE001 - module レベル文の任意例外を仕様違反として分類
                linecache.cache.pop(filename, None)
                raise _wrap_exec_exception(exc, filename=filename, block_id=self.id) from exc
            _verify_structure(cls, self._static_spec, self.id)
            try:
                inner = cls(**self.user_params)
            except TypeError as exc:
                # 静的解析 (params_spec) と exec 後の生成 class で kwarg 名がずれた場合の
                # 生 TypeError を仕様エラーに揃える (通常は起きない = 突合は名前まで一致)。
                raise BlockSpecError(
                    f"PythonFunction[{self.id}]: cannot instantiate the generated block "
                    f"with user_params {sorted(self.user_params)}: {exc}",
                    block_id=self.id,
                ) from exc
            inner.id = self.id
            self._inner = inner
            self._exec_ns = ns
        self.x0 = np.asarray(self._inner.x0, dtype=float)

    @contextmanager
    def _user_frame_guard(self) -> Iterator[None]:
        """ユーザーコードの例外を ``PythonFunctionEvalError`` に包み直す境界。

        ``FlodeError`` (= ``_pack_y`` 等の shape 不一致 ``BlockSpecError`` を含む) は
        そのまま伝播させる。
        """
        try:
            yield
        except FlodeError:
            raise
        except Exception as exc:  # noqa: BLE001 - ユーザーコード境界: 任意例外を構造化して再送出
            raise _wrap_user_exception(
                exc, filename=self._source_filename, block_id=self.id
            ) from exc

    def _inner_or_raise(self) -> Block:
        if self._inner is None:
            raise BlockSpecError(
                f"PythonFunction[{self.id}]: not built yet; run it through Simulator "
                f"(or call _build()) before evaluating.",
                block_id=self.id,
            )
        return self._inner

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        inner = self._inner_or_raise()
        with self._user_frame_guard():
            return inner.output(t, x, u)

    def _synced_inner(self) -> Block:
        """内包インスタンスに ``_resolved_sample_time`` を転送して返す。

        ADR-0073 §論点 3 (V4): 継承 sample_time (-1.0) の解決値は outer に書かれるが、
        デコレータ生成 class は self (= inner) の同名属性を読む。転送を忘れると継承
        ブロックが常に連続扱いになる (= 静かな数値バグ) ので、``derivative`` /
        ``update`` の両方がこの 1 箇所を通る。
        """
        inner = self._inner_or_raise()
        inner._resolved_sample_time = self._resolved_sample_time
        return inner

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        inner = self._synced_inner()
        with self._user_frame_guard():
            return inner.derivative(t, x, u)

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        inner = self._synced_inner()
        with self._user_frame_guard():
            return inner.update(t, x, u)

    def reset(self) -> None:
        """内包インスタンスが ``reset`` を持つ場合のみ委譲する (``run()`` は ``_build`` 後に呼ぶ)。"""
        inner = self._inner
        reset = getattr(inner, "reset", None) if inner is not None else None
        if callable(reset):
            with self._user_frame_guard():
                reset()
