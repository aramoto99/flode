"""SPEC-0016 / ADR-0066 (v0.39.0+): FileWriter の網羅テスト。

v0.39.1 amendment: auto-save (path / format param + _finalize lifecycle) の
テストを追加。
"""

from __future__ import annotations

import csv as csv_module
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import FileWriter, Sine
from pyflw.exceptions import BlockSpecError, FileWriteError


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
            _BLOCK_TRANSLATIONS["pyflw.blocks.file_writer.FileWriter"]["ja"]["display_name"]
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


# ===========================================================================
# SPEC-0016 v0.39.1 amendment: auto-save (path / format param + _finalize)
# ===========================================================================


class TestAutoSaveConstruction:
    def test_default_path_empty(self) -> None:
        fw = FileWriter()
        assert fw.path == ""
        assert fw.format == "auto"

    def test_format_csv_explicit(self) -> None:
        fw = FileWriter(path="out.csv", format="csv")
        assert fw.format == "csv"
        assert fw._resolved_format == "csv"

    def test_format_npz_explicit(self) -> None:
        fw = FileWriter(path="data.npz", format="npz")
        assert fw._resolved_format == "npz"

    def test_format_auto_infers_csv(self) -> None:
        fw = FileWriter(path="result.csv")
        assert fw._resolved_format == "csv"

    def test_format_auto_infers_npz(self) -> None:
        fw = FileWriter(path="result.NPZ")
        # 拡張子は大文字小文字無視
        assert fw._resolved_format == "npz"

    def test_format_auto_unknown_extension_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="cannot infer format"):
            FileWriter(path="out.txt")

    def test_format_invalid_enum_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="format must be one of"):
            FileWriter(format="xml")  # type: ignore[arg-type]

    def test_path_persisted_in_params(self) -> None:
        fw = FileWriter(path="out.csv")
        assert fw._params["path"] == "out.csv"
        assert fw._params["format"] == "auto"


class TestAutoSaveAtRunEnd:
    """``path`` 指定時に ``Simulator.run()`` 終了時に自動 save される。"""

    def test_auto_save_csv(self, tmp_path: Path) -> None:
        out_path = tmp_path / "auto.csv"
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(FileWriter(n_inputs=1, labels=["sine"], path=str(out_path), id="fw"))
        sim.connect("src", "fw")
        sim.run()
        assert out_path.exists()
        with out_path.open() as f:
            rows = list(csv_module.reader(f))
        assert rows[0] == ["time", "sine"]
        assert len(rows) > 1

    def test_auto_save_npz(self, tmp_path: Path) -> None:
        out_path = tmp_path / "auto.npz"
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path=str(out_path), id="fw"))
        sim.connect("src", "fw")
        sim.run()
        assert out_path.exists()
        loaded = np.load(out_path)
        assert "time" in loaded.files
        assert "in0" in loaded.files

    def test_no_auto_save_when_path_empty(self, tmp_path: Path) -> None:
        """``path=""`` (旧挙動) では自動 save しない。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, id="fw"))  # path=""
        sim.connect("src", "fw")
        sim.run()
        # tmp_path 配下にファイルは生成されない
        assert list(tmp_path.iterdir()) == []

    def test_auto_save_with_relative_path_uses_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """workspace_root=None (Python 直接実行) で相対パスは CWD 基準。"""
        monkeypatch.chdir(tmp_path)
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path="relative.csv", id="fw"))
        sim.connect("src", "fw")
        sim.run()
        assert (tmp_path / "relative.csv").exists()

    def test_auto_save_handles_path_overwrite(self, tmp_path: Path) -> None:
        """同じ path に 2 回目の run でも上書きできる。"""
        out_path = tmp_path / "overwrite.csv"
        out_path.write_text("stale content\n")
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path=str(out_path), id="fw"))
        sim.connect("src", "fw")
        sim.run()
        # 上書きされている (= "stale" は残っていない)
        assert "stale" not in out_path.read_text()


class TestAutoSaveWorkspaceRoot:
    """SPEC-0016 v0.39.1 + ADR-0041: server 経由実行時の path traversal 防御。"""

    def test_workspace_root_relative_resolves_under_root(self, tmp_path: Path) -> None:
        """``workspace_root`` 指定時、相対パスは workspace 配下に解決。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path="sub/out.csv", id="fw"))
        sim.connect("src", "fw")
        sim._workspace_root = tmp_path
        (tmp_path / "sub").mkdir()
        sim.run()
        assert (tmp_path / "sub" / "out.csv").exists()

    def test_workspace_root_blocks_escape(self, tmp_path: Path) -> None:
        """``../`` で workspace 外を狙うと FileWriteError (PathTraversalError ラップ)。"""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path="../escape.csv", id="fw"))
        sim.connect("src", "fw")
        sim._workspace_root = workspace
        with pytest.raises(FileWriteError, match="escapes workspace root"):
            sim.run()

    def test_workspace_root_blocks_absolute_outside(self, tmp_path: Path) -> None:
        """workspace 外への絶対パスも reject。"""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside.csv"
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path=str(outside), id="fw"))
        sim.connect("src", "fw")
        sim._workspace_root = workspace
        with pytest.raises(FileWriteError):
            sim.run()


class TestAutoSavePersistence:
    """``path`` / ``format`` が ``.flw.json`` round-trip で保持される。"""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(
            FileWriter(
                n_inputs=2,
                labels=["x", "y"],
                path="output.csv",
                format="csv",
                id="fw_persist",
            )
        )
        model_path = tmp_path / "model.flw.json"
        sim.save(str(model_path))

        sim_loaded = Simulator.load(str(model_path))
        fw_loaded = sim_loaded.get_block("fw_persist")
        assert isinstance(fw_loaded, FileWriter)
        assert fw_loaded.path == "output.csv"
        assert fw_loaded.format == "csv"
        assert fw_loaded._resolved_format == "csv"


class TestAutoSaveErrorPropagation:
    """``_finalize`` の例外が ``FileWriteError`` で構造化される。"""

    def test_block_id_in_error(self, tmp_path: Path) -> None:
        """FileWriteError は block_id kwarg を保持 (ADR-0056)。"""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Sine(id="src"))
        sim.add(FileWriter(n_inputs=1, path="../escape.csv", id="fw_struct_err"))
        sim.connect("src", "fw_struct_err")
        sim._workspace_root = workspace
        with pytest.raises(FileWriteError) as exc_info:
            sim.run()
        assert exc_info.value.block_id == "fw_struct_err"
