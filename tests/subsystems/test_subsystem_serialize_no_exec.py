"""bug-fix: ``Simulator.save()`` / ``Subsystem.to_dict()`` がネスト
PythonFunction のユーザーコードを exec してしまう問題の再現・回帰テスト。

原因: ``Subsystem.to_dict()`` が整合性チェック目的で ``self._build()`` を呼び
(subsystem.py の意図的な設計)、それが ``PythonFunction._build()`` の
``exec_block_source`` に連鎖していた。修正は「シリアライズ目的の build では
ユーザーコードの exec だけを抑止する」(整合性チェック自体は維持する)。

発見の経緯: SPEC-0027 (SM-D Stage 0) の security review 中に発覚
(SPEC-0027 §Stage 1〜3 への引き継ぎ (7))。``load`` / ``from_dict`` は
もともと exec しない (非対称だった)。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from flode import Simulator
from flode.blocks.mathops import Gain
from flode.blocks.pythonfunc import PythonFunction
from flode.blocks.sources import Constant
from flode.exceptions import AlgebraicLoopError, ModelSerializationError
from flode.subsystems import Inport, Outport, Subsystem


def _pf_code(marker: Path) -> str:
    """module レベルで marker ファイルを書く sentinel コード (exec 検知用)。"""
    return textwrap.dedent(
        f"""
        open({str(marker)!r}, "w").write("executed")

        @block
        def f(t: float, u: float) -> float:
            return u
        """
    )


def _nested_pf_subsystem(marker: Path) -> Subsystem:
    return Subsystem(
        blocks=[
            Inport(port_idx=0, id="ip"),
            PythonFunction(code=_pf_code(marker), id="pf"),
            Outport(port_idx=0, id="op"),
        ],
        connections=[
            {"src": "ip", "src_port": 0, "dst": "pf", "dst_port": 0},
            {"src": "pf", "src_port": 0, "dst": "op", "dst_port": 0},
        ],
        id="sub",
    )


def _wrap_in_subsystem(inner: Subsystem, wrapper_id: str) -> Subsystem:
    """inner を 1 段深い Subsystem で包む (深いネストの検証用)。"""
    return Subsystem(
        blocks=[Inport(port_idx=0, id="ip"), inner, Outport(port_idx=0, id="op")],
        connections=[
            {"src": "ip", "src_port": 0, "dst": inner.id, "dst_port": 0},
            {"src": inner.id, "src_port": 0, "dst": "op", "dst_port": 0},
        ],
        id=wrapper_id,
    )


class TestSaveDoesNotExecutePythonFunction:
    def test_save_does_not_execute_nested_python_function(self, tmp_path: Path) -> None:
        # 再現テスト: save しただけで module レベルのコードが exec されてはならない
        marker = tmp_path / "executed.txt"
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(_nested_pf_subsystem(marker))
        sim.connect(c, sub)
        sim.save(tmp_path / "m.flw.json")
        assert not marker.exists(), "Simulator.save() が PythonFunction を exec した"

    def test_to_dict_does_not_reach_exec_block_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # exec 到達をスパイで直接固定する (marker 方式より強い構造保証)
        import flode.blocks.pythonfunc as pf_mod

        calls: list[object] = []
        monkeypatch.setattr(pf_mod, "exec_block_source", lambda *a, **k: calls.append((a, k)))
        marker = tmp_path / "executed.txt"
        sub = _nested_pf_subsystem(marker)
        data = sub.to_dict()
        assert calls == [], "Subsystem.to_dict() が exec_block_source に到達した"
        # シリアライズ内容は静的情報 (code param) から従来どおり得られる
        inner_ids = [b["id"] for b in data["params"]["blocks"]]
        assert inner_ids == ["ip", "pf", "op"]

    def test_to_dict_still_runs_integrity_checks(self, tmp_path: Path) -> None:
        # 修正の副作用ガード: to_dict の _build 呼び出しの本来の目的
        # (不完全な Subsystem を save させない) は維持されること
        broken = Subsystem(
            blocks=[Gain(k=1.0, id="g1"), Gain(k=1.0, id="g2")],
            connections=[
                {"src": "g1", "src_port": 0, "dst": "g2", "dst_port": 0},
                {"src": "g2", "src_port": 0, "dst": "g1", "dst_port": 0},
            ],
            id="broken",
        )
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(broken)
        with pytest.raises(AlgebraicLoopError):
            sim.save(tmp_path / "broken.flw.json")

    def test_run_after_save_still_executes_normally(self, tmp_path: Path) -> None:
        # 抑止がシリアライズ区間の外に漏れ残らないこと: save 後の run では
        # 従来どおり exec される (= 実行意味論は不変)
        marker = tmp_path / "executed.txt"
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(_nested_pf_subsystem(marker))
        sim.connect(c, sub)
        sim.save(tmp_path / "m.flw.json")
        assert not marker.exists()
        sim.run()
        assert marker.exists(), "save 後の run() で exec されていない (抑止の漏れ残り)"

    def test_failed_save_does_not_brick_the_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # security-reviewer MUST-1 の回帰ガード: save が途中 (シリアライズ中) で
        # 失敗しても、無効化は登録済みで区間終了時に実行され、モデルは
        # その後も正常に run できる (「不完全 built 状態の永続化」の防止)。
        marker = tmp_path / "executed.txt"
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(_nested_pf_subsystem(marker))
        sim.connect(c, sub)

        original_to_dict = Outport.to_dict
        state = {"raised": False}

        def raising_once(self: Outport) -> dict[str, object]:
            if not state["raised"]:
                state["raised"] = True
                raise ModelSerializationError("injected serialize failure")
            return original_to_dict(self)

        monkeypatch.setattr(Outport, "to_dict", raising_once)
        with pytest.raises(ModelSerializationError):
            sim.save(tmp_path / "m.flw.json")
        assert not marker.exists()
        sim.run()  # save 失敗後もモデルは実行可能でなければならない
        assert marker.exists()


class TestNestedDepth:
    """深さ 2 以上のネスト (code-reviewer SHOULD 2026-09-08)。"""

    def test_deeply_nested_save_does_not_execute(self, tmp_path: Path) -> None:
        # 深さ 3 (wrap ×2) でも exec 抑止が伝播する
        marker = tmp_path / "executed.txt"
        sub: Subsystem = _nested_pf_subsystem(marker)
        for d in range(2):
            sub = _wrap_in_subsystem(sub, f"wrap{d}")
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sim.connect(c, sub)
        sim.save(tmp_path / "m.flw.json")
        assert not marker.exists()

    def test_deeply_nested_run_after_save_executes_normally(self, tmp_path: Path) -> None:
        # 遅延無効化がネスト全段に効き、save 後の run で exec 込みの完全再構築が走る
        marker = tmp_path / "executed.txt"
        sub = _wrap_in_subsystem(_nested_pf_subsystem(marker), "wrap0")
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sim.connect(c, sub)
        sim.save(tmp_path / "m.flw.json")
        assert not marker.exists()
        sim.run()
        assert marker.exists()

    @staticmethod
    def _count_builds_for_depth(depth: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
        calls: list[str | None] = []
        original_build = Subsystem._build

        def counting_build(self: Subsystem) -> None:
            calls.append(self.id)
            original_build(self)

        monkeypatch.setattr(Subsystem, "_build", counting_build)
        try:
            inner = Subsystem(
                blocks=[
                    Inport(port_idx=0, id="ip"),
                    Gain(k=2.0, id="g"),
                    Outport(port_idx=0, id="op"),
                ],
                connections=[
                    {"src": "ip", "src_port": 0, "dst": "g", "dst_port": 0},
                    {"src": "g", "src_port": 0, "dst": "op", "dst_port": 0},
                ],
                id="leaf",
            )
            sub = inner
            for d in range(depth - 1):
                sub = _wrap_in_subsystem(sub, f"wrap{d}")
            sim = Simulator(t_end=0.1, dt=0.01)
            c = sim.add(Constant(value=1.0, id="c"))
            sim.add(sub)
            sim.connect(c, sub)
            calls.clear()  # 構築時の build は数えず、save (to_dict) だけを測る
            sim.save(tmp_path / f"deep{depth}.flw.json")
            return len(calls)
        finally:
            monkeypatch.undo()

    def test_build_count_growth_is_polynomial_not_exponential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # code-reviewer MUST / security-reviewer NIT-4 の回帰ガード:
        # 即時キャッシュ無効化 (旧実装) では深さ +3 で build 回数が ×20 超に
        # 発散していた。現行 (最外区間での遅延無効化) は多項式 (O(depth²) 程度、
        # to_dict の二重再帰による) に収まる。深さ 5 → 8 の増加率で指数化の
        # 再発を検知する (二次なら ×2.6 程度、指数なら ×20 前後)。
        builds_5 = self._count_builds_for_depth(5, tmp_path, monkeypatch)
        builds_8 = self._count_builds_for_depth(8, tmp_path, monkeypatch)
        ratio = builds_8 / builds_5
        assert ratio < 4.5, (
            f"_build 回数の増加率が {ratio:.1f} 倍 (5→8 段): "
            "シリアライズ区間の即時キャッシュ無効化による指数化の再発が疑われる "
            f"(depth5={builds_5}, depth8={builds_8})"
        )
        assert builds_8 < 150, f"depth8 の build 回数が過大: {builds_8}"
