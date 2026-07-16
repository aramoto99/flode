"""``flode.compile`` — Codegen + Autodiff (jax-first 統合、ADR-0037)。

``Simulator.compile()`` 経由で Block ベースの動的システムを **pure functional
表現** に変換し、jax の XLA で JIT コンパイルする。:func:`flode.linearize` の
``method="jax"`` (ADR-0026 §「Phase 5+ で再評価」再考トリガー回収) もここに
統合される。

主要 API:

* :class:`CompiledSimulator` — ``Simulator.compile()`` の戻り値 (frozen dataclass)
* :func:`Simulator.compile()` (= :mod:`flode.core.simulator` 側のメソッド)

設計方針 (ADR-0037 §Decision):

* **opt-in**: ``Simulator.compile()`` を呼び出さない限り numpy ホットパスが走る
  (= ADR-0036 §(8) 数値完全不変ガード継承)
* **immutable arrays**: jax 経路は ``Simulator.compile()`` が pure functional view
  を生成、既存 numpy コアは無変更 (Option 1-B、ADR-0037 §(1))
* **64-bit 強制**: ``jax_enable_x64=True`` を遅延設定 (= ML エコシステムへの
  副作用最小化、ADR-0037 §Risks #2)
* **Trigger / Enable control block を内包する Subsystem は Codegen 対象外 (MVP)**:
  ``BlockSpecError`` で明示拒否し ``Simulator.run()`` (numpy hot path) へ誘導。
  Phase 6+ で別 ADR で対応 (ADR-0036 §(9) / ADR-0058 §論点 5 整合)

依存関係:

* ``flode[codegen]`` (= ``jax[cpu]>=0.4``) で本モジュールが利用可能
* 未インストール環境では ``ImportError("flode[codegen] required")`` を ``compile``
  / ``method="jax"`` 呼び出しで明示発出 (silent fallback しない)
"""

from __future__ import annotations

from .compiled_simulator import CompiledSimulator

__all__ = ["CompiledSimulator"]
