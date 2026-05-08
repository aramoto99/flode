"""ADR-0018 §(5) Subsystem の SM-B 境界 + 内部 Inport/Outport の整合性 check。

外側 Subsystem の ``port_shapes_in/out`` と内部 ``Inport(port_shape=...)`` /
``Outport(port_shape=...)`` の shape が一致しない場合に build 時 ``BlockSpecError``
で拒否されることを検証する。

追記 (ADR-0018 テスト補強):
  #A  JSON save/load で Inport(port_shape=(n,)) の port_shape が正しく復元される
  #B  複数 Inport を持つ Subsystem で各 port_shape の整合性 check が独立に走る
  #C  Subsystem 内部に Inport が不足する場合 (n_inputs > 0 だが Inport が足りない)
      の挙動を確認する (既存挙動維持)
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
        sub = Subsystem(n_inputs=1, n_outputs=1)
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "Outport_0")
        sub._build()  # 例外なし

    def test_subsystem_sm_b_in_with_matching_inport(self) -> None:
        """Subsystem.port_shapes_in=((3,),) + Inport(port_shape=(3,)) で整合。"""
        sub = Subsystem(
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=((3,),),
        )
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        sub._build()  # 例外なし
        ip = sub.get_block("Inport_0")
        assert ip.port_shape == (3,)

    def test_subsystem_sm_b_inport_mismatch_raises(self) -> None:
        """Subsystem.port_shapes_in=((3,),) と Inport.port_shape=() の不一致で error。"""
        sub = Subsystem(
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=((3,),),
        )
        sub.add(Inport(port_idx=0))  # default port_shape=()
        with pytest.raises(BlockSpecError, match="port_shapes_in"):
            sub._build()

    def test_subsystem_outport_mismatch_raises(self) -> None:
        """Subsystem.port_shapes_out=((2,),) と Outport.port_shape=(3,) の不一致で error。"""
        sub = Subsystem(
            n_inputs=0,
            n_outputs=1,
            port_shapes_out=((2,),),
        )
        sub.add(Outport(port_idx=0, port_shape=(3,)))
        with pytest.raises(BlockSpecError, match="port_shapes_out"):
            sub._build()


# ---------------------------------------------------------------------------
# 後方互換性: 既存の SM-A Subsystem は変更なしで動く
# ---------------------------------------------------------------------------


class TestSubsystemSmACompat:
    def test_sm_a_subsystem_still_works(self) -> None:
        """ADR-0009 で導入された SM-A Subsystem が ADR-0017/0018 後も動く。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=4.0))
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
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
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
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
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
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
        """SM-B Subsystem を save→load すると外側 ``port_shapes_in/out`` が復元される
        (ADR-0018 §(5) MUST 修正、code-reviewer 検出回帰防止)。

        修正前は ``Subsystem.to_dict`` が ``port_shapes_*`` を保存しなかったため、
        load 後の ``_build`` で内部 Inport の SM-B port_shape と外側の SM-A
        ``()`` が不一致になり ``BlockSpecError`` で壊れていた。
        """
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        # SM-B Subsystem: 外側 (3,) input、内部 Inport(port_shape=(3,))
        sub = Subsystem(
            n_inputs=1,
            n_outputs=1,
            id="sub",
            port_shapes_in=((3,),),
            port_shapes_out=((3,),),
        )
        sub.add(Inport(port_idx=0, port_shape=(3,)))
        sub.add(Outport(port_idx=0, port_shape=(3,)))
        sub.connect("Inport_0", "Outport_0")
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(sub)
        path = tmp / "sm_b_sub.flw.json"
        sim.save(path)

        # JSON に port_shapes_in/out が書き出されている
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        assert sub_entry["params"]["port_shapes_in"] == [[3]]
        assert sub_entry["params"]["port_shapes_out"] == [[3]]

        # load して port_shapes_* が復元される
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
        sub = Subsystem(
            n_inputs=1,
            n_outputs=0,
            id="sub",
            port_shapes_in=((3,),),
        )
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

        注意: Subsystem 内部の Inport は Subsystem.to_dict / _from_dict 経由で
        永続化・復元される。
        """
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=((3,),),
            id="sub",
        )
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

    def test_inport_vector_port_shape_tuple_after_load(self, tmp_path: object) -> None:
        """load 後の Inport.port_shape が (3,) の tuple で復元される。"""
        from pathlib import Path

        tmp = cast(Path, tmp_path)
        sim = Simulator(t_end=0.05, dt=0.01)
        sub = Subsystem(
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=((3,),),
            id="sub",
        )
        sub.add(Inport(port_idx=0, port_shape=(3,), id="ip0"))
        sim.add(sub)
        path = tmp / "inport_vector_load.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sub2 = cast(Subsystem, sim2.get_block("sub"))
        ip2 = cast(Inport, sub2.get_block("ip0"))
        assert ip2.port_shape == (3,)


# ---------------------------------------------------------------------------
# #B: 複数 Inport を持つ Subsystem で各 port_shape が独立に check される
# ---------------------------------------------------------------------------


class TestMultipleInportPortShapeCheck:
    def test_two_inports_both_matching(self) -> None:
        """n_inputs=2 で 2 つの Inport がそれぞれ port_shape に一致する場合 build 成功。"""
        sub = Subsystem(
            n_inputs=2,
            n_outputs=0,
            port_shapes_in=((), (3,)),  # ip0: scalar, ip1: vector
        )
        sub.add(Inport(port_idx=0))  # scalar → match
        sub.add(Inport(port_idx=1, port_shape=(3,)))  # vector → match
        sub._build()  # 例外なし

    def test_two_inports_first_mismatch_raises(self) -> None:
        """2 つの Inport のうち port_idx=0 が不一致で BlockSpecError。"""
        sub = Subsystem(
            n_inputs=2,
            n_outputs=0,
            port_shapes_in=((5,), ()),  # ip0: vector (5,), ip1: scalar
        )
        sub.add(Inport(port_idx=0))  # scalar → mismatch
        sub.add(Inport(port_idx=1))  # scalar → match
        with pytest.raises(BlockSpecError, match="port_shapes_in"):
            sub._build()

    def test_two_inports_second_mismatch_raises(self) -> None:
        """2 つの Inport のうち port_idx=1 が不一致で BlockSpecError。"""
        sub = Subsystem(
            n_inputs=2,
            n_outputs=0,
            port_shapes_in=((), (3,)),  # ip1: vector
        )
        sub.add(Inport(port_idx=0))  # scalar → match
        sub.add(Inport(port_idx=1))  # scalar → mismatch with (3,)
        with pytest.raises(BlockSpecError, match="port_shapes_in"):
            sub._build()

    def test_three_inports_all_matching(self) -> None:
        """n_inputs=3 で 3 つの Inport がすべて一致する場合 build 成功。"""
        sub = Subsystem(
            n_inputs=3,
            n_outputs=0,
            port_shapes_in=((), (), ()),
        )
        for i in range(3):
            sub.add(Inport(port_idx=i))
        sub._build()  # 例外なし


# ---------------------------------------------------------------------------
# #C: Subsystem に Inport が不足する場合の既存挙動 (n_inputs > 0 だが Inport 少ない)
# ---------------------------------------------------------------------------


class TestSubsystemMissingInport:
    def test_missing_inport_raises_on_build(self) -> None:
        """n_inputs=2 なのに Inport が 1 つしかない場合、build で BlockSpecError。"""
        sub = Subsystem(n_inputs=2, n_outputs=0)
        sub.add(Inport(port_idx=0))  # 1 つだけ
        with pytest.raises(BlockSpecError, match="n_inputs=2"):
            sub._build()

    def test_zero_inports_with_n_inputs_zero_passes(self) -> None:
        """n_inputs=0 で Inport が 0 個の場合は build 成功。"""
        sub = Subsystem(n_inputs=0, n_outputs=0)
        sub._build()  # 例外なし

    def test_extra_inport_raises_on_build(self) -> None:
        """n_inputs=1 なのに Inport が 2 つある場合、build で BlockSpecError。"""
        sub = Subsystem(n_inputs=1, n_outputs=0)
        sub.add(Inport(port_idx=0))
        sub.add(Inport(port_idx=1))  # 余分
        with pytest.raises(BlockSpecError, match="n_inputs=1"):
            sub._build()
