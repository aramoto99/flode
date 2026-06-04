"""SPEC-0005 §段階的実装案 / ADR-0056 §F-2 動作確認用の失敗注入モデル生成。

Phase 1 の構造化エラーカテゴリ 5 種を確実に発火させる ``.flw.json`` を
``examples/`` に書き出す。Web GUI で開いて Run すると Error tab に分類済の
エラーが表示されることを確認するためのリファレンス。

Run::

    python examples/generate_failure_cases.py

出力:

* ``examples/failure_algebraic_loop.flw.json`` — algebraic_loop カテゴリ
* ``examples/failure_divide_by_zero.flw.json`` — divide_by_zero カテゴリ
* ``examples/failure_solver.flw.json``         — solver_failure カテゴリ (発散)
* ``examples/failure_start_validation.flw.json`` — start_validation カテゴリ
  (=  schema が壊れていて Simulator.load で失敗するモデル。
  .flw.json は手書きで生成する)

shape_mismatch は単一ブロックの connect だけでは再現が難しいため
(= 動的 port 解決で接続時に弾かれるため)、本スクリプトでは生成しない。
手動テスト時は Python 経由で ``np.add(np.zeros(3), np.zeros(2))`` 相当を起こす
カスタムブロックを作る必要がある (= Phase 2 ``user_expression`` カテゴリで対応)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pyflw import Simulator
from pyflw.blocks import Constant, Divide, From, Gain, Integrator, Scope

_logger = logging.getLogger(__name__)


def _algebraic_loop(out_dir: Path) -> None:
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(Gain(k=1.0, id="a"))
    sim.add(Gain(k=1.0, id="b"))
    sim.connect("a", "b")
    sim.connect("b", "a")
    sim.save(out_dir / "failure_algebraic_loop.flw.json")


def _divide_by_zero(out_dir: Path) -> None:
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(Constant(value=1.0, id="num"))
    sim.add(Constant(value=0.0, id="den"))
    sim.add(Divide(signs="*/", id="div"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("num", "div", dst_idx=0)
    sim.connect("den", "div", dst_idx=1)
    sim.connect("div", "scope")
    sim.save(out_dir / "failure_divide_by_zero.flw.json")


def _solver_failure(out_dir: Path) -> None:
    # 高ゲイン正帰還 + 連続積分 = 急発散。RK45 が atol/rtol 内で step を縮め切れず失敗。
    sim = Simulator(t_end=10.0, dt=0.01, atol=1e-12, rtol=1e-12)
    sim.add(Constant(value=1e6, id="src"))
    sim.add(Gain(k=1e6, id="k_fb"))
    sim.add(Integrator(id="int1"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "int1")
    sim.connect("int1", "k_fb")
    sim.connect("k_fb", "int1")  # 正帰還で急発散
    sim.connect("int1", "scope")
    sim.save(out_dir / "failure_solver.flw.json")


def _goto_from_unresolved(out_dir: Path) -> None:
    """対応する Goto が無い From → ``BlockSpecError`` (start_validation)。

    例外に ``block_id`` が載るため、Log tab のエラーから From ブロックへジャンプ
    できることの確認用 (ADR-0056 follow-up)。
    """
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(From(tag="aa", id="From_0"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("From_0", "scope")
    sim.save(out_dir / "failure_goto_from.flw.json")


def _start_validation(out_dir: Path) -> None:
    """``Simulator.load`` 時に弾かれる壊れた flw.json を直書きする。

    存在しないブロック type を含める (= UnknownBlockTypeError, start_validation)。
    """
    bad = {
        "schema_version": "1.0",
        "blocks": [{"id": "x", "type": "pyflw.blocks.nonexistent.Foo", "params": {}}],
        "connections": [],
        "config": {"t_end": 1.0, "dt": 0.01, "solver": "RK45"},
    }
    (out_dir / "failure_start_validation.flw.json").write_text(
        json.dumps(bad, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    _algebraic_loop(out_dir)
    _divide_by_zero(out_dir)
    _solver_failure(out_dir)
    _goto_from_unresolved(out_dir)
    _start_validation(out_dir)
    _logger.info("Generated 5 failure-case models in %s", out_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
