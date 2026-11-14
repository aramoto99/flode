from __future__ import annotations

import warnings
from collections import deque
from typing import TYPE_CHECKING, Any, Literal, get_args

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError, BufferOverflowWarning

if TYPE_CHECKING:
    from matplotlib.axes import Axes


# ADR-0042 §論点 2-A: ring/bounded のデフォルト容量。100,000 サンプル × n_inputs
# float64 で ~800 KB / signal、Scope 5 個 × 8 signals でも ~32 MB と妥当。
_DEFAULT_SCOPE_CAPACITY = 100_000

ScopeBufferMode = Literal["ring", "bounded", "unbounded"]


def _expand_column_labels(labels: list[str], shapes: tuple[tuple[int, ...], ...]) -> list[str]:
    """ポートごとのラベルを列 (C order の要素) ごとのラベルに展開する (ADR-0079 §(4))。

    - ``len(labels) == 総列数`` なら列ごとのラベルとしてそのまま使う
    - ``len(labels) == ポート数`` ならポートラベルを展開する: ``()`` のポートは
      ``label`` のまま、``(n,)`` は ``label[0]`` … ``label[n-1]``、``(m, n)`` は
      ``label[0,0]`` … (C order)
    - どちらでもなければ呼び出し側 (信号面解決器) が build エラーにするので、
      ここでは列数に合わせて末尾を切り詰め / 連番で補う (防御的)
    """
    n_columns = int(sum(int(np.prod(s, dtype=np.int64)) for s in shapes))
    if len(labels) == n_columns and len(labels) != len(shapes):
        return list(labels)
    if len(labels) == len(shapes):
        expanded: list[str] = []
        for label, shape in zip(labels, shapes, strict=True):
            if shape == ():
                expanded.append(label)
                continue
            for index in np.ndindex(*shape):
                expanded.append(f"{label}[{','.join(str(i) for i in index)}]")
        return expanded
    if len(labels) == n_columns:
        return list(labels)
    padded = list(labels[:n_columns])
    padded.extend(f"col{i}" for i in range(len(padded), n_columns))
    return padded


class _VectorSinkMixin:
    """ベクトル入力を受理するシンク共通の ``output_v`` (ADR-0079 §(4))。

    シンクは出力を持たないので ``output_v`` は常に空 tuple。値の記録は
    ``Simulator._record_v`` が各ポートを C order で列展開した 1D ndarray を
    ``record`` に渡す。``_apply_input_shapes`` は Simulator が plan 構築後に
    呼ぶ runtime hook で、列数とラベルを確定する。
    """

    labels: list[str]
    n_inputs: int

    def _apply_input_shapes(self, shapes: tuple[tuple[int, ...], ...]) -> None:
        """信号面解決の in shape から列ラベルを確定する (Simulator が呼ぶ)。"""
        self._column_shapes: tuple[tuple[int, ...], ...] | None = tuple(shapes)
        self._column_labels: list[str] = _expand_column_labels(
            list(self.labels), self._column_shapes
        )

    @property
    def column_labels(self) -> list[str]:
        """記録列ごとのラベル (ベクトル入力は ``in0[0]`` 等に展開、スカラは ``labels`` と同一)。"""
        column_labels = getattr(self, "_column_labels", None)
        if column_labels is None:
            return list(self.labels)
        return list(column_labels)

    @property
    def n_columns(self) -> int:
        """記録列数 (= 全入力ポートの総要素数。plan 未適用なら ``n_inputs``)。"""
        shapes = getattr(self, "_column_shapes", None)
        if shapes is None:
            return int(self.n_inputs)
        return int(sum(int(np.prod(s, dtype=np.int64)) for s in shapes))

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return ()


class Scope(_VectorSinkMixin, Block):
    """シミュレーション中の信号値を時系列で記録し、``plot()`` で可視化する。

    各時刻 ``t`` の入力 ``u`` を ``record(t, u)`` で蓄積する。``values`` プロパティ
    で形状 ``(n_samples, n_columns)`` の ndarray を取得できる。ベクトル入力
    (ADR-0079 §(4)) はポートごとに C order で列展開されるので、全ポートがスカラなら
    ``n_columns == n_inputs`` (従来どおり)。

    Args:
        n_inputs: 記録する信号数 (= 入力ポート数)。
        labels: 各信号のラベル (省略時は ``in0``, ``in1`` ...)。``plot`` で凡例に使う。
            ベクトル入力ではポートラベルを ``in0[0]`` 等に展開する (``column_labels``)。
            列ごとのラベルを直接与えてもよい (要素数 = 総列数)。
        buffer_mode: バッファ動作 (ADR-0042 §論点 2-A)。``"ring"`` (default) は
            ``buffer_capacity`` 到達後に最古サンプルから FIFO drop (= ``Stop Time
            = inf`` の長時間実行で OOM 防止)。``"bounded"`` は capacity 到達で
            ``BufferOverflowWarning`` を 1 回発し以降は record を黙って捨てる
            (= 直近サンプル保持を諦め、初期実行を保つ)。``"unbounded"`` は上限
            なしで無限に成長 — ``Simulator.t_end = inf`` と組み合わせると build
            時に ``BlockSpecError`` で reject される。
        buffer_capacity: ``ring`` / ``bounded`` の容量 (sample 数)。default
            ``100_000`` (ADR-0042 §論点 2-A)。``unbounded`` では未使用。
    """

    # 型エイリアス ScopeBufferMode を単一の真実とし、validation /
    # エラーメッセージ / GUI dropdown ヒントはすべてここから導出する
    # (= 値追加時の更新漏れを防ぐ)。
    _BUFFER_MODES: tuple[str, ...] = get_args(ScopeBufferMode)
    # ADR-0039 follow-up: GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"buffer_mode": _BUFFER_MODES}

    def __init__(
        self,
        n_inputs: int = 1,
        labels: list[str] | None = None,
        *,
        buffer_mode: ScopeBufferMode = "ring",
        buffer_capacity: int = _DEFAULT_SCOPE_CAPACITY,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self.labels = labels or [f"in{i}" for i in range(n_inputs)]
        if buffer_mode not in self._BUFFER_MODES:
            allowed = " / ".join(repr(m) for m in self._BUFFER_MODES)
            raise BlockSpecError(f"Scope: buffer_mode must be {allowed}, got {buffer_mode!r}")
        if buffer_mode != "unbounded" and buffer_capacity < 1:
            raise BlockSpecError(f"Scope: buffer_capacity must be >= 1, got {buffer_capacity!r}")
        self.buffer_mode: ScopeBufferMode = buffer_mode
        self.buffer_capacity: int = int(buffer_capacity)
        # ring/bounded は deque/list で実装、unbounded は list (= 既存挙動)
        self.times: list[float] | deque[float]
        self._values: list[npt.NDArray[Any]] | deque[npt.NDArray[Any]]
        self._init_buffers()
        # bounded で warning 発火済かどうか (= 1 回だけ)
        self._overflow_warned: bool = False
        self._params = {
            "n_inputs": int(n_inputs),
            "labels": self.labels,
            "buffer_mode": self.buffer_mode,
            "buffer_capacity": self.buffer_capacity,
        }

    def _init_buffers(self) -> None:
        """buffer_mode に応じて times / _values を初期化する。"""
        if self.buffer_mode == "ring":
            self.times = deque(maxlen=self.buffer_capacity)
            self._values = deque(maxlen=self.buffer_capacity)
        else:
            # bounded / unbounded は list で持つ (= bounded は capacity 到達後
            # append を skip、unbounded は無制限に append、いずれも numpy 変換が
            # 既存と同じ list[ndarray] パスで効く)
            self.times = []
            self._values = []

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def reset(self) -> None:
        self._init_buffers()
        self._overflow_warned = False

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        if self.buffer_mode == "bounded" and len(self.times) >= self.buffer_capacity:
            if not self._overflow_warned:
                warnings.warn(
                    f"Scope {self.id!r}: buffer_capacity={self.buffer_capacity} "
                    f"reached, dropping further samples (buffer_mode='bounded'). "
                    f"Use buffer_mode='ring' to keep the latest samples instead.",
                    BufferOverflowWarning,
                    stacklevel=2,
                )
                self._overflow_warned = True
            return
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> npt.NDArray[Any]:
        if not self._values:
            return np.empty((0, self.n_columns))
        # deque は np.array() に直接渡せる (= shape は (n_samples, n_columns))
        return np.array(list(self._values))

    def plot(self, ax: Axes | None = None, show: bool = False) -> Any:
        """記録済みサンプルを matplotlib で折れ線プロットする。

        Note:
            タイトルにはブロック id を使う。日本語などの CJK 文字を含む id
            (ADR-0071) は、matplotlib の既定フォント (DejaVu Sans) では豆腐
            (□) になる。日本語タイトルを表示するには利用側で
            ``matplotlib.rcParams["font.family"]`` に CJK 対応フォントを設定
            すること (Web GUI の Scope はブラウザ描画のため影響しない)。
        """
        import matplotlib.pyplot as plt

        created = ax is None
        if created:
            _, ax = plt.subplots()
        assert ax is not None
        t = np.array(self.times)
        v = self.values
        labels = self.column_labels
        for i in range(v.shape[1]):
            ax.plot(t, v[:, i], label=labels[i] if i < len(labels) else f"col{i}")
        ax.set_xlabel("t")
        ax.legend()
        ax.grid(True)
        ax.set_title(self.id or "Scope")
        if show:
            plt.show()
        return ax


class Display(_VectorSinkMixin, Block):
    """シミュレーション中の現在値を数値表示するブロック (リファレンスツールの Display 相当)。

    Scope と同じ duck-type インタフェース (``record`` / ``times`` / ``values`` /
    ``labels``) を持つため server (ADR-0011) の WebSocket scope batch パイプラインを
    そのまま流用できる。フロント側は ``Display`` を canvas 上のブロックフェースに
    「最新値の大きな数字」として描画する (= 履歴プロットではない)。
    ベクトル入力 (ADR-0079 §(4)) は列展開して 1 要素 1 行で表示する
    (``column_labels`` が ``in0[0]`` 等の行ラベル、``format_latest`` が整形の SSOT)。

    Args:
        n_inputs: 入力ポート数 (>= 1)。複数値を縦に並べて表示する。
        decimals: 小数点以下の桁数 (default 3)。フロント側 formatter のヒント。
        labels: 各信号のラベル (省略時は ``in0``, ``in1`` ...)。
    """

    def __init__(
        self,
        n_inputs: int = 1,
        decimals: int = 3,
        labels: list[str] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if n_inputs < 1:
            raise BlockSpecError(f"Display: n_inputs must be >= 1, got {n_inputs}")
        if decimals < 0:
            raise BlockSpecError(f"Display: decimals must be >= 0, got {decimals}")
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self.decimals = int(decimals)
        self.labels = labels or [f"in{i}" for i in range(n_inputs)]
        self.times: list[float] = []
        self._values: list[npt.NDArray[Any]] = []
        self._params = {
            "n_inputs": int(n_inputs),
            "decimals": self.decimals,
            "labels": self.labels,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def reset(self) -> None:
        self.times = []
        self._values = []

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> npt.NDArray[Any]:
        if not self._values:
            return np.empty((0, self.n_columns))
        return np.array(self._values)

    @property
    def latest(self) -> npt.NDArray[Any] | None:
        """最終 sample の値 ndarray (列展開済み 1D) を返す。データなしのとき ``None``。"""
        if not self._values:
            return None
        return self._values[-1]

    def format_latest(self) -> list[tuple[str, str]]:
        """最新値を ``(列ラベル, 整形済み文字列)`` の列で返す (整形規則の SSOT)。

        ベクトル入力は列展開されているので 1 要素 1 行。データなしのときは
        各列を ``"—"`` で埋める。
        """
        labels = self.column_labels
        latest = self.latest
        if latest is None:
            return [(label, "—") for label in labels]
        rows: list[tuple[str, str]] = []
        for i, label in enumerate(labels):
            value = float(latest[i]) if i < len(latest) else float("nan")
            rows.append((label, f"{value:.{self.decimals}f}"))
        return rows


class XYGraph(Block):
    """``y`` を ``x`` に対してプロットするパラメトリックグラフ (リファレンスツールの XY Graph 相当)。

    入力 0 を x、入力 1 を y として記録する。Scope と同じ duck-type インタフェースを
    持つため server WebSocket パイプラインをそのまま流用できる。フロント側は
    ``XYGraph`` を散布線プロットとして描画する (時間軸ではない)。

    Args:
        x_label: x 軸ラベル (default ``"x"``)。
        y_label: y 軸ラベル (default ``"y"``)。
    """

    def __init__(
        self,
        x_label: str = "x",
        y_label: str = "y",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=2, n_outputs=0)
        self.x_label = str(x_label)
        self.y_label = str(y_label)
        self.labels = [self.x_label, self.y_label]
        self.times: list[float] = []
        self._values: list[npt.NDArray[Any]] = []
        self._params = {"x_label": self.x_label, "y_label": self.y_label}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def reset(self) -> None:
        self.times = []
        self._values = []

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> npt.NDArray[Any]:
        if not self._values:
            return np.empty((0, 2))
        return np.array(self._values)

    def plot(self, ax: Axes | None = None, show: bool = False) -> Any:
        """Matplotlib で y vs x の散布線プロットを描く (CLI / pytest 用)。

        Note:
            タイトルの CJK id は既定フォントで豆腐 (□) になる。
            ``Scope.plot`` の Note を参照 (ADR-0071)。
        """
        import matplotlib.pyplot as plt

        created = ax is None
        if created:
            _, ax = plt.subplots()
        assert ax is not None
        v = self.values
        if v.shape[0] > 0:
            ax.plot(v[:, 0], v[:, 1], "-o", markersize=3)
        ax.set_xlabel(self.x_label)
        ax.set_ylabel(self.y_label)
        ax.grid(True)
        ax.set_title(self.id or "XYGraph")
        if show:
            plt.show()
        return ax


#: ImageDisplay が受理する入力 rank (``(H, W)`` = グレー / ``(H, W, 3)`` = RGB)。
_IMAGE_CHANNELS_RGB = 3
_IMAGE_MAX_LEVEL = 255.0
#: ImageDisplay が受理する最大画素数 (= 1920×1080)。GUI へ毎コマ送るため、
#: これを超える画像は配信量 (WS queue のメモリ) を守るため実行前に拒否する。
IMAGE_MAX_PIXELS = 1920 * 1080


class ImageDisplay(Block):
    """配列信号を画像としてブロック面に表示する (SPEC-0034 / ADR-0082)。

    入力は shape ``(H, W)`` (グレースケール) または ``(H, W, 3)`` (RGB) の 1 ポート。
    値 ``0..vmax`` を輝度 ``0..255`` に写し、範囲外はクリップ、NaN は 0 にする。
    保持するのは最新 1 コマだけで、uint8 で持つ (履歴は持たない)。Web GUI は実行中に
    最新コマをブロック面へ描く。Python からは ``latest_frame`` / ``plot()`` で見る。

    Scope 系の duck-type 名 (``times`` / ``values`` / ``labels``) は意図的に持たない
    (= 数値の時系列配信に乗せない、ADR-0082 §(1))。

    Args:
        vmax: 輝度 255 に対応する入力値 (default ``255.0``)。``0..1`` の画像なら ``1.0``。
    """

    # ADR-0079: 任意 shape の入力を受ける sink (output_v は空 tuple)
    _skip_dual_api_check = True

    def __init__(
        self,
        vmax: float = _IMAGE_MAX_LEVEL,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        vmax_f = float(vmax)
        if not np.isfinite(vmax_f) or vmax_f <= 0.0:
            raise BlockSpecError(f"ImageDisplay: vmax must be finite and > 0, got {vmax!r}")
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=0)
        self.vmax = vmax_f
        self._params = {"vmax": self.vmax}
        self._latest: npt.NDArray[np.uint8] | None = None
        self._frame_time: float | None = None
        self._frame_count = 0

    def _apply_input_shapes(self, shapes: tuple[tuple[int, ...], ...]) -> None:
        """入力 shape が画像として表示できるかを実行前に検査する (Simulator が呼ぶ)。"""
        _check_image_shape(self.id, tuple(shapes[0]) if shapes else ())

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return ()

    def reset(self) -> None:
        self._latest = None
        self._frame_time = None
        self._frame_count = 0

    def record_v(self, t: float, u: tuple[npt.NDArray[Any], ...]) -> None:
        """最新コマを uint8 に変換して保持する (ADR-0081 §論点 5-B の記録経路)。"""
        frame = np.asarray(u[0], dtype=float)
        _check_image_shape(self.id, frame.shape)
        scaled = np.nan_to_num(frame, nan=0.0, posinf=self.vmax, neginf=0.0)
        # 極端に大きな有限値の掛け算は inf になるだけ (直後に 255 へクリップ)
        with np.errstate(over="ignore"):
            scaled = np.clip(scaled * (_IMAGE_MAX_LEVEL / self.vmax), 0.0, _IMAGE_MAX_LEVEL)
        self._latest = np.rint(scaled).astype(np.uint8)
        self._frame_time = float(t)
        self._frame_count += 1

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        """スカラ入力だけのモデル (配列信号を通らない経路) では画像にならないので拒否する。"""
        raise BlockSpecError(
            f"ImageDisplay {self.id!r}: input must be an image array of shape (H, W) or "
            f"(H, W, 3), got a scalar signal"
        )

    @property
    def latest_frame(self) -> npt.NDArray[np.uint8] | None:
        """最新コマ (uint8、shape ``(H, W)`` / ``(H, W, 3)``)。未受信なら ``None``。"""
        return self._latest

    @property
    def frame_time(self) -> float | None:
        """最新コマのシミュレーション時刻。未受信なら ``None``。"""
        return self._frame_time

    @property
    def frame_count(self) -> int:
        """この実行で受け取ったコマ数 (``reset`` で 0)。"""
        return self._frame_count

    def plot(self, ax: Axes | None = None, show: bool = False) -> Any:
        """最新コマを matplotlib ``imshow`` で描く (CLI / pytest 用)。"""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots()
        assert ax is not None
        if self._latest is not None:
            cmap = "gray" if self._latest.ndim == 2 else None
            ax.imshow(self._latest, cmap=cmap, vmin=0, vmax=255)
        ax.set_axis_off()
        ax.set_title(self.id or "ImageDisplay")
        if show:
            plt.show()
        return ax


def _check_image_shape(block_id: str | None, shape: tuple[int, ...]) -> None:
    """``(H, W)`` / ``(H, W, 3)`` (H, W >= 1、画素数 ``IMAGE_MAX_PIXELS`` 以下) 以外を拒否する。"""
    is_gray = len(shape) == 2
    is_rgb = len(shape) == 3 and shape[2] == _IMAGE_CHANNELS_RGB
    if not ((is_gray or is_rgb) and shape[0] >= 1 and shape[1] >= 1):
        raise BlockSpecError(
            f"ImageDisplay {block_id!r}: input must be an image array of shape (H, W) or "
            f"(H, W, 3), got shape {shape}"
        )
    if shape[0] * shape[1] > IMAGE_MAX_PIXELS:
        raise BlockSpecError(
            f"ImageDisplay {block_id!r}: image of {shape[0]}x{shape[1]} pixels exceeds the "
            f"limit of {IMAGE_MAX_PIXELS} pixels (1920x1080); downscale it first"
        )


class Terminator(Block):
    """入力を消費するだけで何もしない終端ブロック。

    リファレンスツールの Terminator 相当。使われない出力ポートを終端させて未接続警告を
    避ける用途で使う。任意 shape の入力を受理する (ADR-0079 §(4))。

    Args:
        n_inputs: 入力ポート数 (>= 1)。
    """

    # ADR-0079: ベクトル入力も消費する (output_v は空 tuple)
    _skip_dual_api_check = True

    def __init__(
        self,
        n_inputs: int = 1,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if n_inputs < 1:
            raise BlockSpecError(f"Terminator: n_inputs must be >= 1, got {n_inputs}")
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self._params = {"n_inputs": int(n_inputs)}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return ()
