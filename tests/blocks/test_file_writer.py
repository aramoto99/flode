"""SPEC-0016 / ADR-0066 (v0.39.0): FileWriter の網羅テスト。"""

from __future__ import annotations

import csv as csv_module
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import FileWriter, Sine
from pyflw.exceptions import BlockSpecError


class TestConstruction:
    def test_defaults(self) -> None:
        fw = FileWriter()
        assert fw.n_inputs == 1
        assert fw.n_outputs == 0
        assert fw.labels == ["in0"]

    def test_custom_labels(self) -> None:
        fw = FileWriter(n_inputs=2, labels=["x", "y"])
        assert fw.labels == ["x", "y"]

    def test_n_inputs_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n_inputs must be >= 1"):
            FileWriter(n_inputs=0)

    def test_labels_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must equal n_inputs"):
            FileWriter(n_inputs=2, labels=["only_one"])


class TestSaveNpz:
    def test_round_trip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(FileWriter(n_inputs=1, labels=["sine"], id="fw"))
        sim.connect("src", "fw")
        sim.run()
        fw = sim.get_block("fw")
        out = tmp_path / "out.npz"
        fw.save_npz(out)
        # load back and verify
        data = np.load(out)
        assert "time" in data.files
        assert "sine" in data.files
        np.testing.assert_array_equal(data["time"], np.array(fw.times))
        np.testing.assert_array_equal(data["sine"], fw.values[:, 0])

    def test_multi_inputs(self, tmp_path: Path) -> None:
        fw = FileWriter(n_inputs=3, labels=["a", "b", "c"])
        fw.record(0.0, np.array([1.0, 2.0, 3.0]))
        fw.record(0.1, np.array([4.0, 5.0, 6.0]))
        out = tmp_path / "out.npz"
        fw.save_npz(out)
        data = np.load(out)
        np.testing.assert_array_equal(data["a"], [1.0, 4.0])
        np.testing.assert_array_equal(data["b"], [2.0, 5.0])
        np.testing.assert_array_equal(data["c"], [3.0, 6.0])


class TestSaveCsv:
    def test_round_trip(self, tmp_path: Path) -> None:
        fw = FileWriter(n_inputs=2, labels=["x", "y"])
        fw.record(0.0, np.array([1.0, 2.0]))
        fw.record(0.1, np.array([3.0, 4.0]))
        out = tmp_path / "out.csv"
        fw.save_csv(out)
        # CSV を読み戻して検証
        with out.open(newline="") as f:
            rows = list(csv_module.reader(f))
        assert rows[0] == ["time", "x", "y"]
        assert rows[1] == ["0.0", "1.0", "2.0"]
        assert rows[2] == ["0.1", "3.0", "4.0"]

    def test_empty_buffer(self, tmp_path: Path) -> None:
        fw = FileWriter(n_inputs=1, labels=["a"])
        out = tmp_path / "out.csv"
        fw.save_csv(out)
        with out.open(newline="") as f:
            rows = list(csv_module.reader(f))
        # header のみ
        assert rows == [["time", "a"]]


class TestRecordAndReset:
    def test_record_stores_samples(self) -> None:
        fw = FileWriter(n_inputs=1)
        fw.record(0.0, np.array([1.0]))
        fw.record(0.1, np.array([2.0]))
        assert fw.times == [0.0, 0.1]
        assert fw.values.shape == (2, 1)

    def test_reset_clears_buffer(self) -> None:
        fw = FileWriter(n_inputs=1)
        fw.record(0.0, np.array([1.0]))
        fw.reset()
        assert fw.times == []
        assert fw.values.shape == (0, 1)


class TestRegistry:
    def test_registered(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        assert "pyflw.blocks.file_writer.FileWriter" in _BUILTIN_METADATA
        cat, _, _ = _BUILTIN_METADATA["pyflw.blocks.file_writer.FileWriter"]
        assert cat == "sinks"
        assert (
            _BLOCK_TRANSLATIONS["pyflw.blocks.file_writer.FileWriter"]["ja"][
                "display_name"
            ]
            == "ファイル出力"
        )


class TestInModel:
    def test_full_workflow(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(amplitude=2.0, frequency=1.0, id="src"))
        sim.add(FileWriter(n_inputs=1, labels=["sine"], id="fw"))
        sim.connect("src", "fw")
        sim.run()
        fw = sim.get_block("fw")
        # 結果が蓄積されている
        assert len(fw.times) >= 3
        # save_npz が成功する
        npz_path = tmp_path / "out.npz"
        fw.save_npz(npz_path)
        assert npz_path.exists()
        # save_csv が成功する
        csv_path = tmp_path / "out.csv"
        fw.save_csv(csv_path)
        assert csv_path.exists()
