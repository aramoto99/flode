"""ADR-0018 §(5) Subsystem の SM-B 境界 + 内部 Inport/Outport の整合性 check。

ADR-0039 (v2.0): ``Subsystem.n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
``port_shapes_out`` は内部 ``Inport`` / ``Outport`` から派生する property に
変更された。「外側宣言と内部 port_shape の不一致 raises」テストは仕様上不可能
となったため削除し、以下の派生確認テストに置き換えた:

  - 内部 Inport の port_shape から ``port_shapes_in`` が派生する
  - port_idx 重複 / 抜けは ``BlockSpecError`` で検出される

追記 (ADR-0018 テスト補強、ADR-0039 で書き換え):
  #A  JSON save/load で Inport(port_shape=(n,)) の port_shape が正しく復元される
      (= 派生 property は JSON に保存しないが、内部 Inport の port_shape は保存される
      ので load 後に派生で復元)
  #B  複数 Inport を持つ Subsystem の派生 ``port_shapes_in`` 確認
  #C  Subsystem 内部の port_idx 連番違反 (重複 / 抜け) の挙動
"""

from __future__ import annotations

import json
from typing import cast

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Gain, Scope
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems import Inport, Outport, Subsystem

# ---------------------------------------------------------------------------
# port_shape 整合性 check
# ---------------------------------------------------------------------------


class TestSubsystemPortShapeCheck:
    def test_inport_outport_default_scalar_subsystem_default(self) -> None:
        """既存 SM-A モデル: Subsystem も Inport/Outport も default ``()``。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "Outport_0")
        sub._build()  # 例外なし

    def test_subsystem_sm_b_in_derived_from_inner_inport(self) -> None:
        """ADR-0039: ``port_shapes_in`` は内部 Inport.port_shape から派生する。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        # 派生 property: 内部 Inport の port_shape がそのまま外側に見える
        assert sub.port_shapes_in == ((3,),)
        ip = sub.get_block("Inport_0")
        assert ip.port_shape == (3,)
        sub._build()  # 例外なし

    def test_subsystem_sm_b_out_derived_from_inner_outport(self) -> None:
        """ADR-0039: ``port_shapes_out`` は内部 Outport.port_shape から派生する。"""
        sub = Subsystem()
        sub.add(Outport(port_idx=0, port_shape=(2,)))
        assert sub.port_shapes_out == ((2,),)
        op = sub.get_block("Outport_0")
        assert op.port_shape == (2,)


# ---------------------------------------------------------------------------
# 後方互換性: 既存の SM-A Subsystem は変更なしで動く
# ---------------------------------------------------------------------------


class TestSubsystemSmACompat:
    def test_sm_a_subsystem_still_works(self) -> None:
        """ADR-0009 で導入された SM-A Subsystem が ADR-0017/0018 後も動く。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=4.0))
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "Outport_0")
        sim.add(sub)
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, "sub")
        sim.connect("sub", sc)
        sim.run()
        # Constant(4.0) * Gain(2.0) = 8.0
        arr = np.asarray(sc.values).reshape(-1)
        np.testing.assert_allclose(arr, 8.0 * np.ones_like(arr))


# ---------------------------------------------------------------------------
# Inport / Outport 単体検証
# ---------------------------------------------------------------------------


class TestInportOutportPortShape:
    def test_inport_default_scalar(self) -> None:
        ip = Inport(port_idx=0)
        assert ip.port_shape == ()
        assert ip.port_shapes_out == ((),)

    def test_inport_vector(self) -> None:
        ip = Inport(port_idx=0, port_shape=(5,))
        assert ip.port_shape == (5,)
        assert ip.port_shapes_out == ((5,),)
        # _external_value が ndarray で初期化されている
        assert isinstance(ip._external_value, np.ndarray)
        assert ip._external_value.shape == (5,)

    def test_outport_default_scalar(self) -> None:
        op = Outport(port_idx=0)
        assert op.port_shape == ()
        assert op.port_shapes_in == ((),)

    def test_outport_vector(self) -> None:
        op = Outport(port_idx=0, port_shape=(3,))
        assert op.port_shape == (3,)
        assert op.port_shapes_in == ((3,),)


# ---------------------------------------------------------------------------
# JSON round-trip with SM-B Subsystem
# ---------------------------------------------------------------------------


class TestSubsystemSmBRoundTrip:
    def test_sm_a_subsystem_roundtrip(self, tmp_path: object) -> None:
        """SM-A の Subsystem は port_shape も従来通りシリアライズ。"""
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "Outport_0")
        sim.add(sub)
        path = tmp / "sm_a_sub.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("sub")
        assert sub2.port_shapes_in == ((),)
        assert sub2.port_shapes_out == ((),)

    def test_sm_a_subsystem_json_omits_port_shapes(self, tmp_path: object) -> None:
        """SM-A only の Subsystem は ``port_shapes_in/out`` を JSON に書き出さない
        (= byte-identical 保証、ADR-0018 §(5) MUST 修正)。"""
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "Outport_0")
        sim.add(sub)
        path = tmp / "sm_a_sub.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        assert "port_shapes_in" not in sub_entry["params"]
        assert "port_shapes_out" not in sub_entry["params"]

    def test_sm_b_subsystem_json_roundtrip_preserves_port_shapes(self, tmp_path: object) -> None:
        """ADR-0039: ``port_shapes_in/out`` は派生 property のため JSON には保存しない。
        代わりに内部 Inport / Outport の port_shape が保存され、load 後の派生計算で
        外側 ``port_shapes_*`` が復元される。
        """
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        # ADR-0039: Subsystem() 引数なしで生成、内部 Inport / Outport で port_shape 指定
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        sub.add(Outport(port_idx=0, port_shape=(3,)))
        sub.connect("Inport_0", "Outport_0")
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(sub)
        path = tmp / "sm_b_sub.flw.json"
        sim.save(path)

        # ADR-0039: JSON には port_shapes_in/out フィールドが含まれない (= 派生 property)
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        assert "port_shapes_in" not in sub_entry["params"]
        assert "port_shapes_out" not in sub_entry["params"]

        # load して派生 port_shapes_* が復元される (内部 Inport.port_shape 経由)
        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("sub")
        assert sub2.port_shapes_in == ((3,),)
        assert sub2.port_shapes_out == ((3,),)
        # 内部 Inport も復元され、build が通る
        sub2._build()  # 例外なし


# ---------------------------------------------------------------------------
# SM-B Subsystem の run 拒否 (ADR-0018 §(4.3))
# ---------------------------------------------------------------------------


class TestSubsystemSmBRunRejected:
    def test_sm_b_subsystem_run_raises_block_spec_error(self) -> None:
        """SM-B port を持つ ``Subsystem`` を ``run`` すると build 時に明示エラー。

        ADR-0039: ``port_shapes_in`` は派生 property のため、内部 Inport の
        ``port_shape=(3,)`` から ``((3,),)`` として派生する。SM-B 判定は維持される。
        Subsystem の SM-B 内部実行は ``_step_inner_v`` (Phase 4) を待つ。それまでは
        silent 破損 (SM-A scalar coercion で値が消える) を避けるため
        ``BlockSpecError`` で拒否する (code-reviewer SHOULD 修正)。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0, id="c0"))
        c1 = sim.add(Constant(value=2.0, id="c1"))
        c2 = sim.add(Constant(value=3.0, id="c2"))
        from pyflw.blocks import Mux

        m = sim.add(Mux(n=3, id="m"))
        sub = Subsystem(id="sub")
        # ADR-0039: 内部 Inport の port_shape=(3,) から派生で port_shapes_in=((3,),)
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        sim.add(sub)
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(c2, m, dst_idx=2)
        sim.connect(m, "sub")
        with pytest.raises(BlockSpecError, match="not supported in Phase 3"):
            sim.run()


# ---------------------------------------------------------------------------
# #A: JSON save/load で Inport/Outport の port_shape が正しく復元される
# ---------------------------------------------------------------------------


class TestInportOutportPortShapeJsonRoundTrip:
    def test_inport_vector_port_shape_persisted_in_params(self) -> None:
        """Inport(port_shape=(3,)) の to_dict に port_shape が _params として含まれる。"""
        ip = Inport(port_idx=0, port_shape=(3,), id="ip0")
        d = ip.to_dict()
        assert d["params"]["port_shape"] == [3]

    def test_inport_scalar_port_shape_not_in_params(self) -> None:
        """Inport(port_shape=()) の to_dict には port_shape が _params に含まれない。"""
        ip = Inport(port_idx=0, id="ip0")
        d = ip.to_dict()
        assert "port_shape" not in d["params"]

    def test_outport_vector_port_shape_persisted_in_params(self) -> None:
        """Outport(port_shape=(5,)) の to_dict に port_shape が _params として含まれる。"""
        op = Outport(port_idx=0, port_shape=(5,), id="op0")
        d = op.to_dict()
        assert d["params"]["port_shape"] == [5]

    def test_outport_scalar_port_shape_not_in_params(self) -> None:
        """Outport(port_shape=()) の to_dict には port_shape が _params に含まれない。"""
        op = Outport(port_idx=0, id="op0")
        d = op.to_dict()
        assert "port_shape" not in d["params"]

    def test_inport_vector_port_shape_restored_after_save_load(self, tmp_path: object) -> None:
        """Inport(port_shape=(3,)) を save → load すると port_shape=(3,) で復元される。

        ADR-0039: 外側 ``port_shapes_in`` は派生 property のため JSON には保存しない。
        内部 Inport の ``port_shape`` は保存され、load 後に派生で外側へ復元される。
        """
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, port_shape=(3,), id="ip0"))
        sim.add(sub)

        path = tmp / "inport_vector.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))

        # JSON 構造確認: Subsystem 内部の blocks に Inport が含まれる
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        inner_blocks = sub_entry["params"]["blocks"]
        ip_entry = next(b for b in inner_blocks if b["id"] == "ip0")
        assert ip_entry["params"]["port_shape"] == [3]
        # ADR-0039: 外側 port_shapes_in は JSON に保存しない (= 派生 property)
        assert "port_shapes_in" not in sub_entry["params"]

    def test_inport_vector_port_shape_tuple_after_load(self, tmp_path: object) -> None:
        """load 後の Inport.port_shape が (3,) の tuple で復元される。

        ADR-0039: 派生 ``port_shapes_in`` も内部 Inport.port_shape から自動復元。
        """
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, port_shape=(3,), id="ip0"))
        sim.add(sub)
        path = tmp / "inport_vector_load.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sub2 = cast(Subsystem, sim2.get_block("sub"))
        ip2 = cast(Inport, sub2.get_block("ip0"))
        assert ip2.port_shape == (3,)
        # ADR-0039: 派生 port_shapes_in も復元される
        assert sub2.port_shapes_in == ((3,),)


# ---------------------------------------------------------------------------
# #B: 複数 Inport を持つ Subsystem で各 port_shape が独立に check される
# ---------------------------------------------------------------------------


class TestMultipleInportPortShapeCheck:
    """ADR-0039: 「外側 vs 内部の port_shape 不一致 raises」は派生 property 化に伴い
    廃止。代わりに「複数 Inport の port_shape から外側 ``port_shapes_in`` が正しく
    派生する」ことを確認する。"""

    def test_two_inports_derived_from_inner(self) -> None:
        """2 つの Inport (scalar + vector) から派生 port_shapes_in を確認。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0))  # scalar
        sub.add(Inport(port_idx=1, port_shape=(3,)))  # vector
        assert sub.port_shapes_in == ((), (3,))
        sub._build()  # 例外なし

    def test_inports_derived_in_port_idx_order(self) -> None:
        """port_idx 順 (= add 順とは独立) で派生されることを確認。"""
        sub = Subsystem()
        # 追加順を逆にする (port_idx=1 を先、port_idx=0 を後)
        sub.add(Inport(port_idx=1, port_shape=(3,)))
        sub.add(Inport(port_idx=0))
        # port_idx 順なので scalar が先、vector が後
        assert sub.port_shapes_in == ((), (3,))

    def test_three_inports_all_scalar(self) -> None:
        """3 つの scalar Inport は派生 port_shapes_in == ((), (), ())。"""
        sub = Subsystem()
        for i in range(3):
            sub.add(Inport(port_idx=i))
        assert sub.port_shapes_in == ((), (), ())
        sub._build()  # 例外なし


# ---------------------------------------------------------------------------
# #C: Subsystem に Inport が不足する場合の既存挙動 (n_inputs > 0 だが Inport 少ない)
# ---------------------------------------------------------------------------


class TestSubsystemMissingInport:
    """ADR-0039: ``n_inputs`` 宣言が廃止されたため「宣言と実数の不一致 raises」は
    廃止。代わりに port_idx 連番違反 (重複 / 抜け) は ``BlockSpecError`` で検出。"""

    def test_missing_inport_raises_on_build(self) -> None:
        """ADR-0039: port_idx 抜け (= [0, 2] で 1 が無い) は BlockSpecError。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        sub.add(Inport(port_idx=2))  # gap
        with pytest.raises(BlockSpecError, match=r"do not cover \[0, 2\)"):
            sub._build()

    def test_zero_inports_passes(self) -> None:
        """ADR-0039: 内部 Inport ゼロは派生で n_inputs=0、build 成功。"""
        sub = Subsystem()
        sub._build()  # 例外なし
        assert sub.n_inputs == 0
        assert sub.port_shapes_in == ()

    def test_extra_inport_raises_on_build(self) -> None:
        """ADR-0039: port_idx 重複は BlockSpecError。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        sub.add(Inport(port_idx=0))  # 重複
        with pytest.raises(BlockSpecError, match=r"do not cover \[0, 2\)"):
            sub._build()
