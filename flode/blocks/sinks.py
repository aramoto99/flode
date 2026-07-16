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


class Scope(Block):
    """シミュレーション中の信号値を時系列で記録し、``plot()`` で可視化する。

    各時刻 ``t`` の入力 ``u`` を ``record(t, u)`` で蓄積する。``values`` プロパティ
    で形状 ``(n_samples, n_inputs)`` の ndarray を取得できる。

    Args:
        n_inputs: 記録する信号数 (= 入力ポート数)。
        labels: 各信号のラベル (省略時は ``in0``, ``in1`` ...)。``plot`` で凡例に使う。
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
            return np.empty((0, self.n_inputs))
        # deque は np.array() に直接渡せる (= shape は (n_samples, n_inputs))
        return np.array(list(self._values))

    def plot(self, ax: Axes | None = None, show: bool = False) -> Any:
        import matplotlib.pyplot as plt

        created = ax is None
        if created:
            _, ax = plt.subplots()
        assert ax is not None
        t = np.array(self.times)
        v = self.values
        for i in range(v.shape[1]):
            ax.plot(t, v[:, i], label=self.labels[i])
        ax.set_xlabel("t")
        ax.legend()
        ax.grid(True)
        ax.set_title(self.id or "Scope")
        if show:
            plt.show()
        return ax


class Display(Block):
    """シミュレーション中の現在値を数値表示するブロック (リファレンスツールの Display 相当)。

    Scope と同じ duck-type インタフェース (``record`` / ``times`` / ``values`` /
    ``labels``) を持つため server (ADR-0011) の WebSocket scope batch パイプラインを
    そのまま流用できる。フロント側は ``Display`` を canvas 上のブロックフェースに
    「最新値の大きな数字」として描画する (= 履歴プロットではない)。

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
            return np.empty((0, self.n_inputs))
        return np.array(self._values)

    @property
    def latest(self) -> npt.NDArray[Any] | None:
        """最終 sample の値 ndarray を返す。データなしのとき ``None``。"""
        if not self._values:
            return None
        return self._values[-1]


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
        """Matplotlib で y vs x の散布線プロットを描く (CLI / pytest 用)。"""
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


class Terminator(Block):
    """入力を消費するだけで何もしない終端ブロック。

    リファレンスツールの Terminator 相当。使われない出力ポートを終端させて未接続警告を
    避ける用途で使う。

    Args:
        n_inputs: 入力ポート数 (>= 1)。
    """

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
