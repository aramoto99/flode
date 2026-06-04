"""信号ルーティング系ブロック。

- ``Switch``: 3 入力 1 出力スイッチ (Phase 1)
- ``Mux``: スカラー n 個 → 1D vector (n,) (ADR-0017 SM-B、ADR-0018、Phase 3 #4)
- ``Demux``: 1D vector (n,) → スカラー n 個 (同上)
- ``Goto`` / ``From``: tag ベース仮想配線
  (SPEC-0003 / ADR-0055、Local + Global の 2 visibility)

``Mux`` / ``Demux`` は ADR-0017 で導入された SM-B (ベクトルポート) の最初の
ユーザー向けユースケース。``Goto`` / ``From`` は ``Simulator._execution_order``
内で仮想エッジに展開されるため、実行時には通常の wire と同じ依存グラフに乗る。

Note (Phase 2 送り): ``Scoped`` visibility と ``GotoTagVisibility`` ブロックは
SPEC-0003 / ADR-0055 Amendment (2026-05-19) で Phase 2 送り。Phase 2 で
``tag_visibility`` enum に ``"scoped"`` を追加する形で後方互換的に復活させる予定。
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class Switch(Block):
    """3 入力スイッチ ``y = u[0] if control op threshold else u[2]``。

    入力ポート: ``[input_true, control, input_false]`` の 3 つ。
    ``control`` (= ``u[1]``) が閾値判定をパスすれば ``input_true``、
    そうでなければ ``input_false`` を出力する。

    Args:
        threshold: 比較しきい値。
        criterion: 比較演算子。``">="`` (default) / ``">"`` / ``"!="``。
            リファレンスツールの Switch の "u2 >= Threshold" / "u2 > Threshold" / "u2 ~= 0" 相当。

    Note:
        ``control`` が ``NaN`` のときは Python の比較規則 (NaN との比較は常に
        ``False``、ただし ``!=`` は ``True``) に従い ``input_false`` 側 (``"!="``
        は ``input_true`` 側) が選ばれる。NaN が伝播してきた場合の挙動として
        意図的にこの仕様のまま据え置く (デバッグ時の追跡しやすさは Phase 2 で
        検討)。
    """

    _ALLOWED_CRITERIA = (">=", ">", "!=")
    # ADR-0039 follow-up (v0.15.0): GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"criterion": _ALLOWED_CRITERIA}

    def __init__(
        self,
        threshold: float = 0.0,
        criterion: str = ">=",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if criterion not in self._ALLOWED_CRITERIA:
            raise BlockSpecError(
                f"Switch: criterion must be one of {self._ALLOWED_CRITERIA}, got {criterion!r}"
            )
        super().__init__(id=id, name=name, n_inputs=3, n_outputs=1)
        self.threshold = float(threshold)
        self.criterion = criterion
        self._params = {"threshold": self.threshold, "criterion": criterion}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        control = float(u[1])
        if self.criterion == ">=":
            select_true = control >= self.threshold
        elif self.criterion == ">":
            select_true = control > self.threshold
        else:  # "!="
            select_true = control != self.threshold
        return np.array([float(u[0]) if select_true else float(u[2])])


class Mux(Block):
    """スカラー入力 ``n`` 個を 1D ベクトル (shape ``(n,)``) に集約する。

    ADR-0017 §(7) で API が例示され、ADR-0018 で正式化された SM-B (ベクトルポート)
    の最初のユーザー向けブロック。``direct_feedthrough=True``、状態なし。

    Internal port shape (ADR-0017):
        port_shapes_in  = ((), (), ..., ())  # n 個の rank-0 scalar
        port_shapes_out = ((n,),)            # 1 個の length-n vector

    Args:
        n: 入力ポート数 (= 出力 vector の長さ)。``>= 1`` 必須。

    Raises:
        BlockSpecError: ``n`` が int でない、または ``< 1``。
    """

    # port_shapes は ``n`` から一意に決まるため JSON に出さない (= load 時に
    # ``Mux(n=...)`` から再構築されるので二重持ちは矛盾の元)。ADR-0018 §(1)
    _serialize_port_shapes = False

    def __init__(
        self,
        n: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise BlockSpecError(f"Mux: n must be an int, got {type(n).__name__}")
        if n < 1:
            raise BlockSpecError(f"Mux: n must be >= 1, got {n}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=n,
            n_outputs=1,
            n_states=0,
            direct_feedthrough=True,
            port_shapes_in=tuple(() for _ in range(n)),
            port_shapes_out=((n,),),
        )
        self.n = n
        self._params = {"n": n}

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # 各 u[i] は rank-0 ndarray。float 化して 1D に concat。
        vec = np.array([float(np.asarray(ui).item()) for ui in u], dtype=float)
        return (vec,)


class Demux(Block):
    """1D ベクトル入力 (shape ``(n,)``) を ``n`` 個のスカラーに分解する。

    ADR-0017 §(7) で API が例示され、ADR-0018 で正式化された Demux ブロック。
    ``Mux`` の逆操作。``direct_feedthrough=True``、状態なし。

    Internal port shape (ADR-0017):
        port_shapes_in  = ((n,),)              # 1 個の length-n vector
        port_shapes_out = ((), (), ..., ())    # n 個の rank-0 scalar

    Args:
        n: 入力 vector の長さ (= 出力ポート数)。``>= 1`` 必須。

    Raises:
        BlockSpecError: ``n`` が int でない、または ``< 1``。
    """

    # port_shapes は ``n`` から一意に決まるため JSON に出さない (Mux と同様)。
    _serialize_port_shapes = False

    def __init__(
        self,
        n: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise BlockSpecError(f"Demux: n must be an int, got {type(n).__name__}")
        if n < 1:
            raise BlockSpecError(f"Demux: n must be >= 1, got {n}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=n,
            n_states=0,
            direct_feedthrough=True,
            port_shapes_in=((n,),),
            port_shapes_out=tuple(() for _ in range(n)),
        )
        self.n = n
        self._params = {"n": n}

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        vec = np.asarray(u[0], dtype=float)
        # 各 element を rank-0 ndarray として返す
        return tuple(np.asarray(vec[i], dtype=float) for i in range(self.n))


# ---------------------------------------------------------------------------
# Tag-based virtual wiring (SPEC-0003 / ADR-0055)
# ---------------------------------------------------------------------------

# tag 名の許容文字 / 長さ (SPEC-0003 §5)。非 ASCII は MVP 不可。
_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_TAG_MAX_LEN = 64


def _validate_tag(tag: object, block_name: str) -> str:
    """SPEC-0003 §5 の tag 文字制約を検証する。

    Args:
        tag: 検証対象。``str`` 以外は ``BlockSpecError``。
        block_name: エラーメッセージ用のブロック名 (``"Goto"`` 等)。

    Returns:
        検証済みの tag 文字列。

    Raises:
        BlockSpecError: 非 str / 空文字 / 64 文字超 / 違反文字 (非 ASCII 含む)。
    """
    if not isinstance(tag, str):
        raise BlockSpecError(
            f"{block_name}: tag must be a str, got {type(tag).__name__}"
        )
    if not tag:
        raise BlockSpecError(f"{block_name}: invalid tag name {tag!r} (empty)")
    if len(tag) > _TAG_MAX_LEN:
        raise BlockSpecError(
            f"{block_name}: invalid tag name {tag!r} "
            f"(length {len(tag)} > {_TAG_MAX_LEN})"
        )
    if not _TAG_PATTERN.match(tag):
        raise BlockSpecError(
            f"{block_name}: invalid tag name {tag!r} "
            f"(allowed: ASCII alphanumeric + '_' + '-')"
        )
    return tag


class Goto(Block):
    """Tag ベースの仮想配線送信側 (SPEC-0003 / ADR-0055)。

    入力で受けた信号を ``tag`` に紐付けて公開する。同じ ``tag`` を持つ ``From``
    ブロックが、画面の遠い位置や Subsystem 階層を跨いで参照する。実行時には
    ``Simulator._execution_order`` が仮想エッジに展開する (Goto/From 間の物理
    wire は描画されない)。

    Args:
        tag: 信号 tag (1〜64 文字、ASCII 英数 + ``_`` + ``-``)。
        tag_visibility: ``"local"`` (同一スコープ) / ``"global"`` (モデル全体)。
            default は ``"local"``。``"scoped"`` は Phase 2 送り (SPEC-0003 /
            ADR-0055 Amendment 2026-05-19)、現状の MVP では ``BlockSpecError``。

    Raises:
        BlockSpecError: tag 不正、または ``tag_visibility`` が
            ``("local", "global")`` 以外。

    Note:
        ``output`` / ``output_v`` の戻り値は空 (n_outputs=0)。代わりに入力値を
        ``_last_input`` に保存し、対応 ``From`` ブロックが build 時の解決で
        参照する。SM-A / SM-B 両 path 対応のため ``_skip_dual_api_check`` を
        立てる (ADR-0018 §(5) 内部例外と同じ扱い)。
    """

    # ADR-0018 §(5) と同じ内部例外: SM-A / SM-B 両 path で動作するため両 API 必要
    _skip_dual_api_check = True
    # port_shapes は build 時に上流から確定する (= JSON に出さない、ADR-0017 §(5))。
    _serialize_port_shapes = False
    # SPEC-0003 / ADR-0055 Amendment: ``"scoped"`` は Phase 2 送り。
    # Phase 2 では ``("local", "scoped", "global")`` に拡張する。
    _ALLOWED_VISIBILITY = ("local", "global")
    # ADR-0039 follow-up: Inspector の enum select ヒント
    _param_enums = {"tag_visibility": _ALLOWED_VISIBILITY}

    def __init__(
        self,
        tag: str,
        tag_visibility: str = "local",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        _validate_tag(tag, "Goto")
        if tag_visibility not in self._ALLOWED_VISIBILITY:
            # 旧版 (= Amendment 前) で保存された JSON を load した際に
            # ``"scoped"`` で詰まるケースの移行ガイドを付ける (code-reviewer
            # SHOULD 2026-05-19)。
            hint = (
                " (Note: 'scoped' is deferred to Phase 2 by ADR-0055 Amendment; "
                "use 'global' for cross-scope sharing, or split signals into "
                "Local Goto per Subsystem)"
                if tag_visibility == "scoped"
                else ""
            )
            raise BlockSpecError(
                f"Goto: invalid tag_visibility {tag_visibility!r}, "
                f"must be one of {self._ALLOWED_VISIBILITY}{hint}"
            )
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=0,
            n_states=0,
            direct_feedthrough=True,
        )
        self.tag = tag
        self.tag_visibility = tag_visibility
        self._params = {"tag": tag, "tag_visibility": tag_visibility}
        # build 後・実行時に Goto.output / output_v が書き込み、対応 From が参照する。
        # `None` は「まだ Goto が一度も実行されていない」状態 (= From 側の早期参照
        # を BlockSpecError で気付けるようにする)。
        self._last_input: npt.NDArray[Any] | None = None

    def output(
        self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]
    ) -> npt.NDArray[Any]:
        # SM-A path: u は 1D ndarray shape (1,)。値を保持して空配列を返す
        # (n_outputs=0 のため Simulator._step は y = np.atleast_1d(...) で 1D 長 0)。
        self._last_input = np.asarray(u, dtype=float).copy()
        return np.zeros(0)

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # SM-B path: u は tuple of 1 ndarray (任意 port shape)。値の shape を保持。
        self._last_input = np.asarray(u[0], dtype=float).copy()
        return ()


class From(Block):
    """Tag ベースの仮想配線受信側 (SPEC-0003 / ADR-0055)。

    同じ ``tag`` を持つ ``Goto`` ブロックの入力値をそのまま出力する。visibility
    は持たず、build 時に Local → Global の優先順位で動的解決する
    (Scoped 解決は Phase 2 送り、SPEC-0003 / ADR-0055 Amendment 2026-05-19)。

    Args:
        tag: 信号 tag (Goto と同じ制約)。

    Raises:
        BlockSpecError: tag 不正。

    Note:
        出力 shape は対応 Goto の入力 shape から build 時に推論される
        (ADR-0055 §論点 4)。``direct_feedthrough`` も build 時に ``False``
        (= 未解決状態の安全側 default) から ``True`` に書き換わる
        (= 仮想 wire 経由で Goto 上流に依存するため)。
    """

    _skip_dual_api_check = True
    _serialize_port_shapes = False

    def __init__(
        self,
        tag: str,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        _validate_tag(tag, "From")
        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=1,
            n_states=0,
            # ``Simulator._resolve_goto_from_virtual_edges`` で True に上書き。
            # 上書き前 (= 仮想エッジ展開前) に exec_order に組み込まれないよう、
            # default は False (= 「上流に依存しない」と見なされて先頭に来る) で
            # 開始し、build 後の topo sort では仮想 deps で正しい位置に配置される。
            direct_feedthrough=False,
        )
        self.tag = tag
        self._params = {"tag": tag}
        # build 時に解決済み Goto への参照を持つ。output / output_v はこれを
        # 介して Goto._last_input を返す。
        self._resolved_goto: Goto | None = None

    def _ensure_resolved(self) -> Goto:
        if self._resolved_goto is None:
            raise BlockSpecError(
                f"From {self.id!r}(tag={self.tag!r}): not resolved. "
                f"Did Simulator._resolve_goto_from_virtual_edges run?"
            )
        if self._resolved_goto._last_input is None:
            raise BlockSpecError(
                f"From {self.id!r}(tag={self.tag!r}): upstream Goto "
                f"{self._resolved_goto.id!r} has not produced any output yet. "
                f"This usually indicates a scheduling bug "
                f"(Goto must run before its corresponding From)."
            )
        return self._resolved_goto

    def output(
        self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]
    ) -> npt.NDArray[Any]:
        # SM-A path: 解決済み Goto の _last_input (= 1D shape (1,)) を copy 返却。
        # ADR-0055 §論点 6 (Option 6-A): MVP は 1 copy 固定 (view 最適化は Phase 2)。
        goto = self._ensure_resolved()
        # Goto._last_input は SM-A path で shape (1,)、SM-B path で port_shape。
        # SM-A モードでは From.output は 1D shape (1,) を返す契約 (= n_outputs=1)。
        last = np.asarray(goto._last_input, dtype=float)
        # SM-A モードでは Goto._last_input.shape == (1,)、そのまま 1D で返せる。
        # SM-B モードでは output_v が呼ばれるため本メソッドは通らない。
        return last.copy()

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # SM-B path: 解決済み Goto の _last_input (= port_shape の ndarray) を
        # tuple of 1 ndarray にラップして copy 返却 (ADR-0055 §論点 6)。
        goto = self._ensure_resolved()
        return (np.asarray(goto._last_input, dtype=float).copy(),)


# GotoTagVisibility は SPEC-0003 / ADR-0055 Amendment (2026-05-19) で Phase 2 送り。
# Phase 2 で Scoped visibility と同時に再導入予定。


# ===========================================================================
# SPEC-0014 / ADR-0059 (v5.7.0): Wave 2 第 3 弾 = routing 拡張
# ===========================================================================


class MultiportSwitch(Block):
    """n-input マルチポートスイッチ ``y = u[1 + idx]``。

    入力 ``u[0]`` を selector index (実数 → ``round`` で整数化)、
    ``u[1..n_choices]`` をデータ入力として扱い、idx 番目のデータを出力する。
    既存 ``Switch`` (2 入力 + 条件) の n 入力への一般化。

    Args:
        n_choices: データ入力数 (>= 1、既定 2)。総入力数は ``1 + n_choices``
        index_base: ``"zero"`` (既定、selector 0 → data 0) / ``"one"``
        out_of_range_mode: ``"clip"`` (既定、[0, n_choices-1] に飽和) /
            ``"error"`` (範囲外で BlockEvalError)

    Raises:
        BlockSpecError: ``n_choices < 1``、enum 値外。
        BlockEvalError: ``out_of_range_mode="error"`` で selector が範囲外。
    """

    _ALLOWED_INDEX_BASES: tuple[str, ...] = ("zero", "one")
    _ALLOWED_OOR_MODES: tuple[str, ...] = ("clip", "error")
    _param_enums = {
        "index_base": _ALLOWED_INDEX_BASES,
        "out_of_range_mode": _ALLOWED_OOR_MODES,
    }

    def __init__(
        self,
        n_choices: int = 2,
        index_base: str = "zero",
        out_of_range_mode: str = "clip",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n_choices, int) or isinstance(n_choices, bool):
            raise BlockSpecError(
                f"MultiportSwitch: n_choices must be an int, "
                f"got {type(n_choices).__name__}"
            )
        if n_choices < 1:
            raise BlockSpecError(
                f"MultiportSwitch: n_choices must be >= 1, got {n_choices}"
            )
        if index_base not in self._ALLOWED_INDEX_BASES:
            raise BlockSpecError(
                f"MultiportSwitch: index_base must be one of "
                f"{self._ALLOWED_INDEX_BASES}, got {index_base!r}"
            )
        if out_of_range_mode not in self._ALLOWED_OOR_MODES:
            raise BlockSpecError(
                f"MultiportSwitch: out_of_range_mode must be one of "
                f"{self._ALLOWED_OOR_MODES}, got {out_of_range_mode!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1 + n_choices, n_outputs=1)
        self.n_choices = n_choices
        self.index_base = index_base
        self.out_of_range_mode = out_of_range_mode
        self._params = {
            "n_choices": n_choices,
            "index_base": index_base,
            "out_of_range_mode": out_of_range_mode,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # 遅延 import で循環回避
        from ..exceptions import BlockEvalError

        selector_raw = float(u[0])
        offset = 0 if self.index_base == "zero" else 1
        # round で integer 化 (Python int round half-to-even)
        idx = int(round(selector_raw)) - offset
        if idx < 0 or idx >= self.n_choices:
            if self.out_of_range_mode == "error":
                raise BlockEvalError(
                    f"MultiportSwitch[{self.name}]: selector index {idx} "
                    f"(raw={selector_raw}, base={self.index_base}) "
                    f"out of range [0, {self.n_choices - 1}]",
                    block_id=self.id,
                )
            # clip
            idx = max(0, min(self.n_choices - 1, idx))
        return np.array([float(u[1 + idx])])


class Merge(Block):
    """n 入力 1 出力 priority merge: 最初の non-default 入力を選ぶ。

    Triggered Subsystem 風の「アクティブな入力だけ非デフォルト値を持つ」パターン
    を想定。入力 ``u[0..n_inputs-1]`` を順にスキャンし、``initial_value`` と
    異なる最初の値を出力する。全て一致なら ``initial_value`` を出力する。

    Args:
        n_inputs: 入力ポート数 (>= 1、既定 2)
        initial_value: デフォルト値 (既定 0.0)

    Raises:
        BlockSpecError: ``n_inputs < 1``。
    """

    def __init__(
        self,
        n_inputs: int = 2,
        initial_value: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n_inputs, int) or isinstance(n_inputs, bool):
            raise BlockSpecError(
                f"Merge: n_inputs must be an int, got {type(n_inputs).__name__}"
            )
        if n_inputs < 1:
            raise BlockSpecError(f"Merge: n_inputs must be >= 1, got {n_inputs}")
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self.initial_value = float(initial_value)
        self._params = {
            "n_inputs": n_inputs,
            "initial_value": self.initial_value,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # u[i] != initial_value の最初の値を返す (float 比較は厳密一致でよい:
        # Triggered Subsystem は固定値を出すため境界揺らぎはない)
        for i in range(self.n_inputs):
            val = float(u[i])
            if val != self.initial_value:
                return np.array([val])
        return np.array([self.initial_value])
