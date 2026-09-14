"""SPEC-0010 / ADR-0059 (v5.3.0): RandomSource の網羅テスト。

カバー範囲:
- 構築時検証 (distribution enum、sample_time、low<high、std>0、seed 型)
- uniform / gaussian の統計 (大サンプル、固定 seed)
- sample-time hold (出力は state のみ、同一 t 多重評価で同一値、サンプル境界で更新)
- 決定性 (seed=int で run 間 bit-identical、seed=None で非決定)
- save/load round-trip + 不正データ → ModelLoadError
- registry / i18n 翻訳テーブル
- Simulator 統合 + マルチレート (複数 sample_time のブロックと混在)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Gain, RandomSource, Scope
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.exceptions import BlockSpecError, ModelLoadError

_EMPTY_X = np.array([0.0])
_EMPTY_U = np.array([])


def _build_sim(sample_time: float = 0.01, t_end: float = 1.0, **rs_kwargs) -> Simulator:
    """RandomSource → Scope の最小モデルを構築する。"""
    sim = Simulator(t_end=t_end, dt=sample_time)
    sim.add(RandomSource(sample_time=sample_time, id="rs", **rs_kwargs))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("rs", "sc")
    return sim


def _samples(sim: Simulator) -> np.ndarray:
    return np.asarray(sim.get_block("sc").values)[:, 0]


# ===========================================================================
# Construction & validation
# ===========================================================================


class TestRandomSourceConstruction:
    def test_default_is_uniform(self) -> None:
        blk = RandomSource(sample_time=0.1)
        assert blk.distribution == "uniform"
        assert blk.low == 0.0
        assert blk.high == 1.0
        assert blk.n_inputs == 0
        assert blk.n_outputs == 1
        assert blk.n_states == 1
        assert blk.direct_feedthrough is True
        assert blk._params["seed"] is None

    def test_seed_int(self) -> None:
        blk = RandomSource(sample_time=0.1, seed=42)
        assert blk._params["seed"] == 42

    def test_seed_none_explicit(self) -> None:
        blk = RandomSource(sample_time=0.1, seed=None)
        assert blk._params["seed"] is None

    def test_bad_distribution_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="distribution must be one of"):
            RandomSource(sample_time=0.1, distribution="bogus")

    def test_low_ge_high_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="require low < high"):
            RandomSource(sample_time=0.1, low=1.0, high=0.5)

    def test_low_equals_high_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="require low < high"):
            RandomSource(sample_time=0.1, low=1.0, high=1.0)

    def test_std_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="require std > 0"):
            RandomSource(sample_time=0.1, std=0.0)

    def test_sample_time_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="sample_time must be > 0"):
            RandomSource(sample_time=0.0)

    def test_seed_float_type_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="seed must be int or None"):
            RandomSource(sample_time=0.1, seed=3.14)  # type: ignore[arg-type]

    def test_seed_bool_type_raises(self) -> None:
        """bool は int 派生だが seed として受け取らない。"""
        with pytest.raises(BlockSpecError, match="seed must be int or None"):
            RandomSource(sample_time=0.1, seed=True)  # type: ignore[arg-type]


# ===========================================================================
# Uniform distribution statistics
# ===========================================================================


class TestRandomSourceUniform:
    """大サンプル統計 (固定 seed で確率的失敗を回避)。"""

    @pytest.fixture
    def samples(self) -> np.ndarray:
        sim = _build_sim(
            sample_time=0.001,
            t_end=10.0,
            distribution="uniform",
            low=0.0,
            high=1.0,
            seed=42,
        )
        sim.run()
        # 最初のサンプルを除外 (x0=0.0 placeholder が見える可能性は無いが念のため
        # post-fire 値で評価)
        return _samples(sim)

    def test_range_within_bounds(self, samples: np.ndarray) -> None:
        assert samples.min() >= 0.0
        assert samples.max() <= 1.0

    def test_mean_near_half(self, samples: np.ndarray) -> None:
        # uniform [0, 1] の母平均 0.5、N=10000 で 3σ ≈ 0.009
        assert abs(samples.mean() - 0.5) < 0.02

    def test_variance_near_uniform(self, samples: np.ndarray) -> None:
        # uniform [0, 1] の母分散 1/12 ≈ 0.0833
        assert abs(samples.var() - 1.0 / 12.0) < 0.01


# ===========================================================================
# Gaussian distribution statistics
# ===========================================================================


class TestRandomSourceGaussian:
    @pytest.fixture
    def samples(self) -> np.ndarray:
        sim = _build_sim(
            sample_time=0.001,
            t_end=10.0,
            distribution="gaussian",
            mean=0.0,
            std=1.0,
            seed=42,
        )
        sim.run()
        return _samples(sim)

    def test_mean_near_zero(self, samples: np.ndarray) -> None:
        # gaussian(0, 1) で N=10000、3σ/sqrt(N) ≈ 0.03
        assert abs(samples.mean()) < 0.05

    def test_std_near_one(self, samples: np.ndarray) -> None:
        assert abs(samples.std() - 1.0) < 0.05

    def test_no_extreme_outliers(self, samples: np.ndarray) -> None:
        # gaussian で |x| > 6σ はほぼ起きない (P < 2e-9)
        assert np.max(np.abs(samples)) < 6.0


# ===========================================================================
# Sample-time hold semantics
# ===========================================================================


class TestRandomSourceSampleTimeHold:
    def test_output_is_pure_state_hold(self) -> None:
        """output() は state[0] を返すだけで rng を引かない (同一 x → 同一 y)。"""
        blk = RandomSource(sample_time=0.1, seed=42)
        x = np.array([0.5])
        y1 = blk.output(0.0, x, _EMPTY_U)
        y2 = blk.output(0.0, x, _EMPTY_U)
        y3 = blk.output(0.05, x, _EMPTY_U)
        assert y1[0] == 0.5
        assert y2[0] == 0.5
        assert y3[0] == 0.5  # 中間時刻でも state 値を hold

    def test_update_advances_rng(self) -> None:
        """advance() を 2 回呼ぶと異なる値を返す (rng が進む)。update() は hold (ADR-0078)。"""
        blk = RandomSource(sample_time=0.1, seed=42)
        x0 = np.array([0.0])
        y1 = blk.advance(0.0, x0, _EMPTY_U)
        y2 = blk.advance(0.1, x0, _EMPTY_U)
        assert y1[0] != y2[0]
        np.testing.assert_array_equal(blk.update(0.1, y2, _EMPTY_U), y2)

    def test_state_hold_at_multirate(self) -> None:
        """sample_time > dt のとき、中間ステップでは Scope が前値を見続ける。"""
        # sample_time=0.2, dt_base=0.1 (Sine 由来) → step_ratio=2。
        # 偶数ステップで update fire、奇数ステップでは hold。
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(RandomSource(sample_time=0.2, seed=42, id="rs"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("rs", "sc")
        sim.run()
        ys = _samples(sim)
        # ys[0], ys[2], ys[4], ... は新値、ys[1] == ys[0]、ys[3] == ys[2] のはず
        # (中間ステップで update は呼ばれない)
        assert ys[1] == ys[0]
        assert ys[3] == ys[2]
        assert ys[5] == ys[4]
        # 各サンプル境界で値は変化している
        assert ys[2] != ys[0]
        assert ys[4] != ys[2]


# ===========================================================================
# Determinism (rng reset on Simulator.run() via reset() hook)
# ===========================================================================


class TestRandomSourceDeterminism:
    def test_same_seed_bit_identical_across_two_runs(self) -> None:
        """同一 Simulator + seed=int で 2 回 run → bit-identical。"""
        sim = _build_sim(seed=42)
        sim.run()
        y1 = _samples(sim).copy()
        sim.run()
        y2 = _samples(sim).copy()
        np.testing.assert_array_equal(y1, y2)

    def test_different_seed_different_output(self) -> None:
        sim1 = _build_sim(seed=42)
        sim2 = _build_sim(seed=43)
        sim1.run()
        sim2.run()
        y1 = _samples(sim1)
        y2 = _samples(sim2)
        assert not np.array_equal(y1, y2)

    def test_seed_none_different_across_two_sims(self) -> None:
        """seed=None で異なる Simulator インスタンスは異なる sequence (OS entropy)。"""
        sim1 = _build_sim(seed=None)
        sim2 = _build_sim(seed=None)
        sim1.run()
        sim2.run()
        y1 = _samples(sim1)
        y2 = _samples(sim2)
        # 同じ値が並ぶ確率はほぼ 0 (高 entropy)
        assert not np.array_equal(y1, y2)

    def test_seed_none_different_across_two_runs_on_same_sim(self) -> None:
        """seed=None で reset() が rng 内部 state を更新する (= 非決定の根拠)。

        code-reviewer SHOULD: 統計的に「2 配列が一致しない」確認 (false-positive
        の確率は事実上 0 だが数値根拠が弱い) ではなく、reset() 後に rng の
        bit_generator state が変化したことを直接確認する。
        """
        sim = _build_sim(seed=None)
        sim.run()
        rs = sim.get_block("rs")
        assert isinstance(rs, RandomSource)
        state_before: int = rs._rng.bit_generator.state["state"]["state"]
        sim.run()
        state_after: int = rs._rng.bit_generator.state["state"]["state"]
        assert state_before != state_after


# ===========================================================================
# Persistence (save / load round-trip)
# ===========================================================================


class TestRandomSourcePersistence:
    def test_save_load_round_trip_with_int_seed(self, tmp_path: Path) -> None:
        sim1 = _build_sim(seed=42, distribution="gaussian", mean=1.0, std=0.5)
        path = tmp_path / "model.flw.json"
        sim1.save(path)

        sim2 = Simulator.load(path)
        loaded = sim2.get_block("rs")
        assert isinstance(loaded, RandomSource)
        assert loaded.distribution == "gaussian"
        assert loaded.mean == 1.0
        assert loaded.std == 0.5
        assert loaded._params["seed"] == 42

        # 決定性確認: 元 Sim と load 後 Sim が同じ出力を出す
        sim1.run()
        sim2.run()
        np.testing.assert_array_equal(_samples(sim1), _samples(sim2))

    def test_save_load_round_trip_with_none_seed(self, tmp_path: Path) -> None:
        """seed=None は JSON null で保存・復元される (型が保たれる)。"""
        sim = _build_sim(seed=None)
        path = tmp_path / "model.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("rs")
        assert loaded._params["seed"] is None

    def test_load_with_invalid_data_raises_model_load_error(self, tmp_path: Path) -> None:
        """SPEC-0008 で追加した except 経路で BlockSpecError → ModelLoadError ラップ。"""
        bad_payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {},
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": 0.01,
            },
            "blocks": [
                {
                    "id": "bad",
                    "type": "flode.blocks.random_source.RandomSource",
                    "params": {
                        "sample_time": -0.1,  # 不正
                        "distribution": "uniform",
                        "low": 0.0,
                        "high": 1.0,
                        "mean": 0.0,
                        "std": 1.0,
                        "seed": 42,
                    },
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad.flw.json"
        path.write_text(json.dumps(bad_payload))
        with pytest.raises(ModelLoadError, match="Cannot instantiate block"):
            Simulator.load(path)


# ===========================================================================
# Registry & i18n
# ===========================================================================


class TestRandomSourceRegistry:
    def test_translation_entry_exists(self) -> None:
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["flode.blocks.random_source.RandomSource"]
        assert entry["ja"]["display_name"] == "乱数源"
        assert entry["en"]["display_name"] == "Random Source"

    def test_registry_metadata_entry(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["flode.blocks.random_source.RandomSource"]
        assert cat == "sources"
        assert name == "Random Source"
        assert icon == "sources.random"

    def test_default_factory_args_provides_sample_time(self) -> None:
        """palette drop 時に required ``sample_time`` を補う default args の存在確認。"""
        from flode.server.registry import _BUILTIN_DEFAULT_ARGS

        args = _BUILTIN_DEFAULT_ARGS["flode.blocks.random_source.RandomSource"]
        assert args["sample_time"] > 0


# ===========================================================================
# Integration in Simulator
# ===========================================================================


class TestRandomSourceInModel:
    def test_random_through_gain_to_scope(self, tmp_path: Path) -> None:
        """RandomSource → Gain → Scope モデル + save/load round-trip。"""

        def build() -> Simulator:
            sim = Simulator(t_end=0.5, dt=0.01)
            sim.add(RandomSource(sample_time=0.01, low=-1.0, high=1.0, seed=42, id="rs"))
            sim.add(Gain(k=2.0, id="amp"))
            sim.add(Scope(n_inputs=1, id="sc"))
            sim.connect("rs", "amp")
            sim.connect("amp", "sc")
            return sim

        sim1 = build()
        sim1.run()
        y1 = _samples(sim1).copy()
        # Gain 2x なので [-2, 2] レンジ
        assert y1.min() >= -2.0
        assert y1.max() <= 2.0

        path = tmp_path / "model.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        sim2.run()
        y2 = _samples(sim2)
        np.testing.assert_array_equal(y1, y2)

    def test_multiple_random_sources_independent(self) -> None:
        """2 つの RandomSource (同じ seed) が独立に動作する (相互干渉なし)。"""
        sim = Simulator(t_end=0.5, dt=0.01)
        sim.add(RandomSource(sample_time=0.01, seed=42, id="rs1"))
        sim.add(RandomSource(sample_time=0.01, seed=42, id="rs2"))
        sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect("rs1", "sc", dst_idx=0)
        sim.connect("rs2", "sc", dst_idx=1)
        sim.run()
        values = np.asarray(sim.get_block("sc").values)
        # 同 seed で独立 rng → 同じ sequence を生成 (干渉なし、各 rng が完全独立)
        np.testing.assert_array_equal(values[:, 0], values[:, 1])
