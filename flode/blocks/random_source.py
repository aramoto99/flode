"""SPEC-0010 / ADR-0059 (v5.3.0): Random / Noise source ブロック ``RandomSource``。

業界標準ブロック線図ツールの "Random Number" / "Uniform Random Number" 相当の
確率的入力ソース。サンプル時刻で乱数を引いて hold し、中間時刻は前値を返す
(= 階段関数として下流の連続ブロックに渡る)。`seed` 指定で run 間 bit-identical
の決定性を保証 (CI テスト・回帰検出に必須)。

設計の要点 (ADR-0059 §論点 4、SPEC-0010 §機能要件):

* **sampled (sample_time gated hold)**: 連続 ODE ソルバ ``solve_ivp`` の可変ステップ
  RK 再評価で同一 ``t`` を複数回 query しても、状態 ``x`` を返すだけなので **同一値
  を返す** (積分の連続性 + 再現性確保)。乱数を引くのは ``update`` (サンプル境界
  のみ)、``output`` は state hold のみ
* **n_states=1**: ``ZeroOrderHoldDirect`` と同型の 1-state hold パターン
* **rng reset on run()**: ``reset()`` lifecycle hook で ``np.random.default_rng
  (self._initial_seed)`` を再構築する。同一 Simulator インスタンスで ``run()`` を
  複数回呼んでも、各 run で同一 seed を起点に bit-identical な結果を返す
  (seed=None なら毎回 OS エントロピー → 非決定)
* **direct_feedthrough=True**: ソース (n_inputs=0) は代数ループに寄与しない。
  Block 基底クラスの default も True
* **x0=0.0**: placeholder。Simulator.run() の [A'] → [A] 順序 (ADR-0015) で、
  t=0 のサンプル境界で ``update`` が呼ばれて新乱数で state を上書きするため、
  placeholder 0.0 は ``output`` を通じてユーザーに露出しない
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class RandomSource(Block):
    """サンプル時刻で乱数を引いて hold する確率的入力ソース。

    分布は ``distribution`` enum で切り替える:

    * ``"uniform"`` (既定) — ``rng.uniform(low, high)``
    * ``"gaussian"`` — ``rng.normal(mean, std)``

    不使用パラメータは無視するため、enum 切替時にすべて設定し直す必要はない
    (= UX 配慮)。

    Args:
        sample_time: サンプル周期 [s]、``> 0`` 必須。中間時刻は前値ホールド。
        distribution: ``"uniform"`` または ``"gaussian"``。
        low: uniform の下限 (既定 0.0)。``low < high`` 必須。
        high: uniform の上限 (既定 1.0)。
        mean: gaussian の平均 (既定 0.0)。
        std: gaussian の標準偏差 (既定 1.0)。``> 0`` 必須。
        seed: ``int`` で決定性、``None`` (既定) で OS エントロピー (非決定)。

    Raises:
        BlockSpecError: ``distribution`` enum 外 / ``sample_time <= 0`` /
            ``low >= high`` / ``std <= 0`` / ``seed`` が ``int | None`` 以外 /
            numpy 側で ``seed`` が範囲外。

    Note:
        ``low >= high`` / ``std <= 0`` の検証は ``distribution`` に関係なく実行する
        (= 後で distribution を切り替えたときの罠を回避する safety net)。

        ``Simulator.compile()`` (ADR-0037 codegen + GPU jax) 経路では
        ``np.random.Generator`` が XLA トレース不可なため fallback 対象になる。

    Example:
        >>> # uniform [0, 1] (既定)、seed 指定で決定性
        >>> rs = RandomSource(sample_time=0.1, seed=42)
        >>> # uniform [-1, 1]、非決定
        >>> rs = RandomSource(sample_time=0.01, low=-1.0, high=1.0)
        >>> # gaussian (平均 0, std 0.5)、seed 指定
        >>> rs = RandomSource(
        ...     sample_time=0.001,
        ...     distribution="gaussian", mean=0.0, std=0.5,
        ...     seed=123,
        ... )
    """

    _ALLOWED_DISTRIBUTIONS: tuple[str, ...] = ("uniform", "gaussian")
    # ADR-0019 / ADR-0039 follow-up: GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"distribution": _ALLOWED_DISTRIBUTIONS}

    def __init__(
        self,
        *,
        sample_time: float,
        distribution: str = "uniform",
        low: float = 0.0,
        high: float = 1.0,
        mean: float = 0.0,
        std: float = 1.0,
        seed: int | None = None,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if distribution not in self._ALLOWED_DISTRIBUTIONS:
            raise BlockSpecError(
                f"RandomSource: distribution must be one of "
                f"{self._ALLOWED_DISTRIBUTIONS}, got {distribution!r}"
            )
        if not isinstance(sample_time, (int, float)) or isinstance(sample_time, bool):
            raise BlockSpecError(
                f"RandomSource: sample_time must be a number, got {type(sample_time).__name__}"
            )
        if sample_time <= 0.0:
            raise BlockSpecError(f"RandomSource: sample_time must be > 0, got {sample_time}")
        # 後で distribution を切り替えたときの罠を回避するため、両方の制約を強制する。
        if not (low < high):
            raise BlockSpecError(
                f"RandomSource: require low < high for uniform, got [{low}, {high}]"
            )
        if std <= 0.0:
            raise BlockSpecError(f"RandomSource: require std > 0 for gaussian, got {std}")
        # bool は int 派生だが、論理値を seed として受け取らない (型の意図と乖離)。
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise BlockSpecError(
                f"RandomSource: seed must be int or None, got {type(seed).__name__}"
            )
        try:
            rng = np.random.default_rng(seed)
        except (OverflowError, ValueError) as exc:
            raise BlockSpecError(f"RandomSource: invalid seed {seed!r}: {exc}") from exc

        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=True,  # ソース、代数ループには寄与しない
            sample_time=sample_time,
        )

        self.distribution = distribution
        self.low = float(low)
        self.high = float(high)
        self.mean = float(mean)
        self.std = float(std)
        # reset() が hot path で参照する seed snapshot (=
        # Simulator.run() のたびに rng を再構築するため)。
        self._initial_seed: int | None = seed
        self._rng: np.random.Generator = rng

        # x0=0.0 placeholder。Simulator.run() の [A'] update → [A] output 順序
        # (ADR-0015) で、t=0 のサンプル境界で新乱数で上書きされるため、ユーザーには
        # 露出しない。
        self.x0 = np.array([0.0])

        self._params: dict[str, Any] = {
            "distribution": distribution,
            "low": self.low,
            "high": self.high,
            "mean": self.mean,
            "std": self.std,
            "sample_time": float(sample_time),
            "seed": seed,
        }

    def reset(self) -> None:
        """``Simulator.run()`` 開始時の lifecycle hook (simulator.py:1004-1006)。

        rng を初期 ``seed`` から再構築することで、同一モデル + 同一 ``seed`` での
        複数回 run が bit-identical な出力を返す決定性を保証する。``seed=None``
        では ``np.random.default_rng(None)`` が OS エントロピーから新たな state を
        引くため、run ごとに異なる sequence になる (非決定)。
        """
        self._rng = np.random.default_rng(self._initial_seed)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # state hold: 中間時刻でも同一 t 多重評価でも同一値を返す。
        return np.array([float(x[0])])

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # サンプル境界 (Simulator が k % step_ratio == 0 で fire) でのみ呼ばれる。
        # ここで rng を進めて新値を state に書く。output は次回呼出からこの値を hold する。
        if self.distribution == "uniform":
            return np.array([float(self._rng.uniform(self.low, self.high))])
        # gaussian
        return np.array([float(self._rng.normal(self.mean, self.std))])
