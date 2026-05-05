"""LTI ブロック共通ユーティリティ (ADR-0006)。

連続版と離散版の SS / TF ブロックで共有する定数とヘルパーを置く。
"""

from __future__ import annotations

# ADR-0006 §(6): D 行列の最大絶対値がこの閾値を超えたら direct_feedthrough = True
_DF_TOLERANCE = 1e-12
