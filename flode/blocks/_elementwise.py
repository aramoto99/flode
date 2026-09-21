"""要素ごと演算ブロック共通の ``output_v`` (ADR-0079 §(3) D-5)。

Stage 1 の直達ブロック (``Gain`` / ``Sum`` / ``Saturation`` / 比較・論理系 …) は
:class:`ElementwiseMixin` を継承し、テンソル対応の計算を ``_kernel`` に書く。
``output_v`` は ``_kernel`` を呼ぶだけ、SM-A の ``output`` は **1 バイトも変えない**
(D-5: 既存モデルの bit 不変)。

契約:

- ``_kernel(t, x, u)`` は各入力ポートの ndarray のタプルを受け取り、各出力ポートの
  ndarray のタプルを返す。入力 shape は信号面解決器の合流規則 (D-4: 完全一致 +
  rank-0 スカラ拡張のみ) を満たしていることが保証されている
- 出力 shape は解決器の ``elementwise`` 規則 (= 全入力の合流 shape) と一致すること。
  ``Simulator._output_v_cast`` が plan と突合して不一致を ``BlockSpecError`` にする
- 全入力が rank-0 のとき ``_kernel`` の各出力は ``output`` と bit-identical であること
  (AC-11、``tests/blocks/test_elementwise_vector.py`` が parametrize で固定)
- dtype は素通し (予測 dtype への cast は ``_step_vector`` の 1 箇所)

MRO 上は ``Block`` の **前** に置く (``class Gain(ElementwiseMixin, Block)``)。
``Block.__init__`` の dual-override 検査は leaf の ``__dict__`` だけを見るので、
mixin に ``output_v`` があっても leaf が ``output`` だけを定義していれば通る。
信号面解決器は MRO 名 ``ElementwiseMixin`` で ``elementwise`` 規則を引くため、
拡張ブロックも本 mixin を継承するだけで要素ごと規則に乗る。
"""

from __future__ import annotations

from typing import Any

import numpy.typing as npt


class ElementwiseMixin:
    """``output_v`` を ``_kernel`` へ委譲する mixin (状態を持たない)。"""

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        """テンソル対応の出力計算。サブクラスが実装する。

        Args:
            t: 現時刻。
            x: 現状態 (要素ごと演算ブロックは通常空)。
            u: 各入力ポートの ndarray のタプル (rank-0 を含む任意 shape)。

        Returns:
            各出力ポートの ndarray のタプル。
        """
        raise NotImplementedError(f"{type(self).__name__}._kernel not implemented")

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        """SM-T vector-port API: ``_kernel`` の呼び出し 1 行 (ADR-0079 §(3))。"""
        return self._kernel(t, x, u)
