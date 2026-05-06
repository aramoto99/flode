"""Block 基底クラス。

ADR-0002 (離散時間サポート) で `sample_time` 属性と `update` メソッドを追加。
ADR-0004 (ブロック ID 規則) で `id` 属性を正式名として導入し、`name` を後方互換 alias 化。
ADR-0003 (`@block` DSL) で `_params` 辞書をオプション属性として宣言 (デコレータ生成 class
が書き込む。Phase 2 JSON save/load で参照予定)。
ADR-0017 (信号モデル SM-B) で ``port_shapes_in`` / ``port_shapes_out`` 属性と
``output_v`` メソッドを追加 (各ポートが任意 shape の ndarray を運ぶベクトルポート)。
SM-A (各ポート = 1 スカラー) は ``port_shapes = ()`` (rank-0) の特殊ケースとして表現。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..exceptions import BlockSpecError
from .identifiers import validate_block_id

# ADR-0017 §(3): SM-A 互換 (rank-0 scalar) を表す port shape
_SCALAR_SHAPE: tuple[int, ...] = ()


def _normalize_port_shapes(
    port_shapes: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None,
    n_ports: int,
    side: str,
) -> tuple[tuple[int, ...], ...]:
    """``port_shapes_in`` / ``port_shapes_out`` を tuple-of-tuples に正規化する。

    Args:
        port_shapes: ユーザー指定の port shapes、または ``None`` (= 全 SM-A scalar)。
        n_ports: 期待ポート数 (``n_inputs`` または ``n_outputs``)。
        side: エラーメッセージ用 ("in" / "out")。

    Returns:
        ``tuple[tuple[int, ...], ...]`` 形式 (常に長さ ``n_ports``)。

    Raises:
        BlockSpecError: 長さ不一致、shape の要素が int でない、負の dim 等。
    """
    if port_shapes is None:
        return tuple(_SCALAR_SHAPE for _ in range(n_ports))
    if not isinstance(port_shapes, (list, tuple)):
        raise BlockSpecError(
            f"port_shapes_{side}: must be a sequence of shapes, got {type(port_shapes).__name__}"
        )
    if len(port_shapes) != n_ports:
        port_count_name = "n_inputs" if side == "in" else "n_outputs"
        raise BlockSpecError(
            f"port_shapes_{side}: length {len(port_shapes)} does not match "
            f"{port_count_name}={n_ports}"
        )
    normalized: list[tuple[int, ...]] = []
    for i, shape in enumerate(port_shapes):
        if not isinstance(shape, (list, tuple)):
            raise BlockSpecError(
                f"port_shapes_{side}[{i}]: must be a tuple of ints (got {type(shape).__name__})"
            )
        dims: list[int] = []
        for j, d in enumerate(shape):
            if not isinstance(d, (int, np.integer)) or isinstance(d, bool):
                raise BlockSpecError(
                    f"port_shapes_{side}[{i}][{j}]: each dim must be an int (got "
                    f"{type(d).__name__})"
                )
            d_int = int(d)
            if d_int < 0:
                raise BlockSpecError(
                    f"port_shapes_{side}[{i}][{j}]: dim must be non-negative, got {d_int}"
                )
            dims.append(d_int)
        normalized.append(tuple(dims))
    return tuple(normalized)


class Block:
    """全ブロックの基底クラス。

    Attributes:
        id: ブロック識別子。`None` の場合は ``Simulator.add`` で自動採番される。
        n_inputs: 入力ポート数。
        n_outputs: 出力ポート数。
        n_states: 状態次元数 (連続/離散とも n_states に集約)。
        direct_feedthrough: True なら入力 ``u`` が出力 ``y`` に直接影響する。
            False のブロック (Integrator, UnitDelay 等) が代数ループを切る。
        sample_time: ``None`` または ``0.0`` で連続、``> 0`` で離散周期 [s]、
            ``-1.0`` で上流から継承 (Simulator がビルド時に解決)。
        x0: 初期状態 (shape ``(n_states,)``)。
        input_sources: 各入力ポートの接続元 ``(Block, output_idx)``。``None`` は未接続。
        port_shapes_in: 各入力ポートの shape (``tuple[tuple[int, ...], ...]``)。
            default は全 ``()`` (rank-0 scalar、SM-A 互換)。ADR-0017 SM-B。
        port_shapes_out: 各出力ポートの shape。同様 default 全 ``()``。

    Note:
        ADR-0017 SM-B: ベクトルポートを使うブロックは ``port_shapes_in`` /
        ``port_shapes_out`` を明示的に指定し、``output_v`` をオーバーライドする。
        SM-A (scalar-only) ブロックは default のままで動作 (``output`` のみ実装)。
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        n_inputs: int = 1,
        n_outputs: int = 1,
        n_states: int = 0,
        direct_feedthrough: bool = True,
        sample_time: float | None = None,
        port_shapes_in: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        port_shapes_out: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
    ) -> None:
        if id is not None and name is not None:
            raise BlockSpecError("id and name cannot both be set; use id (name is a Phase 0 alias)")
        resolved_id = id if id is not None else name
        if resolved_id is not None:
            validate_block_id(resolved_id)
        self._id: str | None = resolved_id

        if sample_time is not None:
            if not isinstance(sample_time, (int, float)):
                raise BlockSpecError(
                    f"sample_time must be a number or None, got {type(sample_time).__name__}"
                )
            st = float(sample_time)
            if st < 0.0 and st != -1.0:
                raise BlockSpecError(
                    f"sample_time={st} is invalid. Allowed: None, 0.0 (continuous), "
                    f">0 (discrete period), or -1.0 (inherited)."
                )
            sample_time = st

        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.n_states = n_states
        self.direct_feedthrough = direct_feedthrough
        self.sample_time: float | None = sample_time
        self.x0: np.ndarray = np.zeros(n_states)
        self.input_sources: list[tuple[Block, int] | None] = [None] * n_inputs

        # ADR-0017 SM-B: port shapes (default 全 () = SM-A scalar)
        self.port_shapes_in: tuple[tuple[int, ...], ...] = _normalize_port_shapes(
            port_shapes_in, n_inputs, "in"
        )
        self.port_shapes_out: tuple[tuple[int, ...], ...] = _normalize_port_shapes(
            port_shapes_out, n_outputs, "out"
        )

        # ADR-0017 §(8) U3: ``output`` と ``output_v`` の両方を **leaf class で直接**
        # 定義するのは禁止 (実行時 check)。``cls.__dict__`` で直接定義されているか
        # 判定することで、Subsystem 等のフレームワーク内部実装が ``output`` を
        # override していても、leaf サブクラスが ``output_v`` のみを override した
        # ケースを誤検出しない (code-reviewer MUST 修正)。
        cls = type(self)
        output_in_leaf = "output" in cls.__dict__
        output_v_in_leaf = "output_v" in cls.__dict__
        if output_in_leaf and output_v_in_leaf:
            raise BlockSpecError(
                f"{cls.__name__}: must override either `output` (SM-A) or `output_v` (SM-B), "
                f"not both. SM-A blocks should use `output` only; SM-B-aware blocks (e.g. "
                f"Mux/Demux with vector ports) should use `output_v`."
            )

        self._resolved_sample_time: float | None = None
        self._step_ratio: int = 1
        # ``@block`` デコレータ生成 class がパラメータを格納する場所 (ADR-0003 §(5))。
        # 直接 ``Block`` 継承で書かれたブロックでは空のまま。Phase 2 JSON save/load
        # で参照予定。
        self._params: dict[str, Any] = {}

    @property
    def id(self) -> str | None:
        """ブロック識別子 (read-write)。

        Simulator に登録済みのブロックの ID を直接書き換えるのは未サポート。
        リネームは ``Simulator.rename(old, new)`` を使うこと。
        """
        return self._id

    @id.setter
    def id(self, value: str | None) -> None:
        if value is not None:
            validate_block_id(value)
        self._id = value

    @property
    def name(self) -> str | None:
        """Phase 0 後方互換 alias for ``id`` (read-only)。

        Phase 1 では deprecation 警告を出さない。Phase 2 リリース時に
        ``DeprecationWarning`` を発する判断を予定 (ADR-0004)。
        """
        return self._id

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """SM-A scalar-port API でブロック出力 ``y(t, x, u)`` を計算する。

        各 input/output port が rank-0 scalar (= SM-A 互換、port_shapes 全 ``()``) の
        ブロックはこのメソッドをオーバーライドする。ベクトルポート (= SM-B、任意
        shape ndarray) を扱うブロックは代わりに ``output_v`` を実装する。

        Args:
            t: 現時刻。
            x: 現状態 (shape ``(n_states,)``)。状態を持たないブロックは空配列。
            u: 現入力 (shape ``(n_inputs,)``)。``direct_feedthrough=False`` のブロック
                では出力計算 1 パス目で ``u`` がゼロ埋めされる場合がある。

        Returns:
            出力ベクトル (shape ``(n_outputs,)``)。
        """
        raise NotImplementedError(f"{self.__class__.__name__}.output not implemented")

    def output_v(
        self,
        t: float,
        x: np.ndarray,
        u: tuple[np.ndarray, ...],
    ) -> tuple[np.ndarray, ...]:
        """SM-B vector-port API でブロック出力を計算する (ADR-0017 §(3))。

        各 input port が任意 shape ndarray を運ぶ vector-aware ブロック (Mux, Demux,
        将来の MIMO ブロック等) はこのメソッドをオーバーライドする。

        Default 実装は SM-A 互換 wrapper (ADR-0017 §(8) U1):
        ``u: tuple[ndarray, ...]`` を 1D ndarray に flatten し、既存 ``output`` を
        呼び、戻り値を tuple of rank-0 ndarrays に分解する。これにより全 SM-A
        ブロックは ``output`` のみ実装で動作する (改修ゼロ)。

        Args:
            t: 現時刻。
            x: 現状態 (shape ``(n_states,)``)。
            u: 各入力ポートの ndarray のタプル。``len(u) == n_inputs``、各 ``u[i]``
                の shape は ``port_shapes_in[i]``。

        Returns:
            各出力ポートの ndarray のタプル。``len(...) == n_outputs``、各要素の
            shape は ``port_shapes_out[i]``。
        """
        # SM-A wrapper: 全 port shape が () の場合のみ動作する。
        # 各 u[i] は rank-0 ndarray (shape ()) なので float 化して 1D に集約。
        u_flat = np.array([float(np.asarray(ui).item()) for ui in u], dtype=float)
        x_arr = np.asarray(x, dtype=float)
        y_flat = np.atleast_1d(np.asarray(self.output(t, x_arr, u_flat), dtype=float))
        # ADR-0017 §(8) U1: ユーザーカスタム SM-A ブロックの実装ミス (n_outputs と
        # output() 戻り値 shape の不一致) を sandbox 化する。SM-A hot path
        # (`Simulator._step` 直呼び) ではこの check は走らないため、SM-B モードでの
        # 安全網として機能する (code-reviewer MUST 修正)。
        if y_flat.shape != (self.n_outputs,):
            raise BlockSpecError(
                f"{type(self).__name__}.output must return shape ({self.n_outputs},), "
                f"got {y_flat.shape}"
            )
        # 各出力 port を rank-0 ndarray として分解
        return tuple(np.asarray(y_flat[i], dtype=float) for i in range(self.n_outputs))

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """連続状態の時間微分 ``x_dot(t, x, u)`` を返す。

        Default 実装は ``np.zeros(n_states)`` を返す。連続状態を持つブロックは
        オーバーライドする。``sample_time > 0`` の離散ブロックでは呼ばれない。
        """
        return np.zeros(self.n_states)

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """離散ブロックの状態更新 ``x_next = update(t, x, u)`` を返す。

        Args:
            t: 現サンプル時刻。
            x: 現状態 (shape ``(n_states,)``)。
            u: 現入力 (shape ``(n_inputs,)``)。

        Returns:
            次サンプル時刻の状態 (shape ``(n_states,)``)。

        Note:
            Default 実装は ``x`` をそのまま返す (組合せ論理のみの離散ブロック用)。
            実装側は **新しい ndarray を返す** こと。in-place 更新すると Simulator の
            double buffering が破綻する。
        """
        return x

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._id!r}>"

    def _build(self) -> None:
        """構造解析 (実行順、direct_feedthrough、状態 layout 等) を確定する hook。

        ``Simulator._execution_order`` がトポロジカル解析を始める前に呼ばれる。
        Default 実装は no-op。``Subsystem`` のように内部構造を持つブロックが
        override し、``self.direct_feedthrough`` / ``self.n_states`` / ``self.x0``
        等の値を **解析前に**確定する責務を持つ。
        """
        return

    def to_dict(self) -> dict[str, Any]:
        """ブロックを JSON-serializable な辞書に変換する (ADR-0008 §(5))。

        各サブクラスは ``__init__`` で ``self._params`` にユーザー API キーワード
        引数を記録する責務を持つ。``@block`` デコレータ生成 class は
        ``ADR-0003 §(5)`` で既に ``_params`` を保持する。

        Returns:
            ``{"id": ..., "type": "module.ClassName", "params": {...}}``。

        Raises:
            ModelSerializationError: class が ``__main__`` モジュールで定義されている
                場合、または ``_params`` に JSON-serializable でない値が含まれる場合。
        """
        from .persistence import block_type_path, to_json_dict

        out: dict[str, Any] = {
            "id": self._id,
            "type": block_type_path(self.__class__),
            "params": to_json_dict(self._params),
        }
        # ADR-0017 §(5) / SM-B: port_shapes は default 全 () (= SM-A scalar) のとき
        # 省略、SM-B-aware ブロック (どこか非 () の port shape) のときのみ JSON に
        # 出力する (code-reviewer SHOULD 修正、Phase 3 #4 Mux/Demux save/load 対応)。
        scalar_shape: tuple[int, ...] = ()
        if any(s != scalar_shape for s in self.port_shapes_in):
            out["port_shapes_in"] = [list(s) for s in self.port_shapes_in]
        if any(s != scalar_shape for s in self.port_shapes_out):
            out["port_shapes_out"] = [list(s) for s in self.port_shapes_out]
        return out
