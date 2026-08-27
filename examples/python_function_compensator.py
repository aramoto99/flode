"""SPEC-0023 / ADR-0073 (v0.49.0): PythonFunction (p-function) デモ。

``Fcn`` の 1 行式では書けない **状態あり + 分岐あり** のロジックを、GUI と同じ
``@block`` 形のソース文字列で ``PythonFunction`` ブロックに埋め込む。
ここでは飽和付きの 1 次遅れ補償器 (= 出力を ±limit にクリップしつつ内部状態を
持つ) を書き、Sine 入力に対する応答を Scope に記録する。

セキュリティ: ``PythonFunction`` はサンドボックスされない。モデルを実行する =
``code`` の内容を自分の権限で実行する、と理解して使うこと (SPEC-0023 §5)。
"""

from __future__ import annotations

import logging
import textwrap

import numpy as np

from flode import Simulator
from flode.blocks import PythonFunction, Scope, Sine

_logger = logging.getLogger(__name__)

# GUI の「Python Function」ブロックに貼るソースと同一。ポート数 (1 in / 1 out)、
# 状態数 (1)、パラメータ (tau / limit) は静的解析で決まり、exec は run() 直前に
# 1 回だけ起きる。
COMPENSATOR_CODE = textwrap.dedent(
    """
    @block(states=1, direct_feedthrough=True)
    def saturating_lag(
        t: float, x: np.ndarray, u: float, *, tau: float = 0.1, limit: float = 0.8
    ) -> tuple[float, np.ndarray]:
        \"\"\"1 次遅れ (時定数 tau) の出力を ±limit で飽和させる補償器。\"\"\"
        y = max(-limit, min(limit, x[0]))
        x_dot = np.array([(u - x[0]) / tau])
        return y, x_dot
    """
)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
    sim.add(
        PythonFunction(
            code=COMPENSATOR_CODE,
            user_params={"tau": 0.05, "limit": 0.7},
            id="compensator",
        )
    )
    sim.add(Scope(n_inputs=2, labels=["src", "compensated"], id="trace"))

    sim.connect("src", "compensator")
    sim.connect("src", "trace", dst_idx=0)
    sim.connect("compensator", "trace", dst_idx=1)

    sim.run()

    values = np.asarray(sim.get_block("trace").values)
    src = values[:, 0]
    comp = values[:, 1]
    _logger.info("samples: %d", len(values))
    _logger.info("src range: [%.3f, %.3f]", src.min(), src.max())
    _logger.info("compensated range: [%.3f, %.3f] (limit=0.7)", comp.min(), comp.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
