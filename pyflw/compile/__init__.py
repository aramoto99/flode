"""``pyflw.compile`` — Codegen + Autodiff (jax-first 統合、ADR-0037)。

``Simulator.compile()`` 経由で Block ベースの動的システムを **pure functional
表現** に変換し、jax の XLA で JIT コンパイルする。:func:`pyflw.linearize` の
``method="jax"`` (ADR-0026 §「Phase 5+ で再評価」再考トリガー回収) もここに
統合される。

主要 API:

* :class:`CompiledSimulator` — ``Simulator.compile()`` の戻り値 (frozen dataclass)
* :func:`Simulator.compile()` (= :mod:`pyflw.core.simulator` 側のメソッド)

設計方針 (ADR-0037 §Decision):

* **opt-in**: ``Simulator.compile()`` を呼び出さない限り numpy ホットパスが走る
  (= ADR-0036 §(8) 数値完全不変ガード継承)
* **immutable arrays**: jax 経路は ``Simulator.compile()`` が pure functional view
  を生成、既存 numpy コアは無変更 (Option 1-B、ADR-0037 §(1))
* **64-bit 強制**: ``jax_enable_x64=True`` を遅延設定 (= ML エコシステムへの
  副作用最小化、ADR-0037 §Risks #2)
* **TriggeredSubsystem は Codegen out-of-scope**: v0.17.x では ``BlockSpecError``
  で明示拒否、Phase 6+ で別 ADR (ADR-0036 §(9) と整合)

依存関係:

* ``pyflw[codegen]`` (= ``jax[cpu]>=0.4``) で本モジュールが利用可能
* 未インストール環境では ``ImportError("pyflw[codegen] required")`` を ``compile``
  / ``method="jax"`` 呼び出しで明示発出 (silent fallback しない)
"""

from __future__ import annotations

from .compiled_simulator import CompiledSimulator

__all__ = ["CompiledSimulator"]
