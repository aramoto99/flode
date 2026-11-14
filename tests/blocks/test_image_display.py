"""SPEC-0034 F-1〜F-4: ImageDisplay ブロックのテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode.blocks import Constant, ImageDisplay
from flode.core.simulator import Simulator
from flode.exceptions import BlockSpecError


def _run_with_image(value: object, *, vmax: float = 255.0, t_end: float = 0.2) -> ImageDisplay:
    sim = Simulator(t_end=t_end, dt=0.1)
    src = sim.add(Constant(value=value, id="src"))
    disp = sim.add(ImageDisplay(vmax=vmax, id="disp"))
    sim.connect(src, disp)
    sim.run()
    return disp


class TestAcceptedShapes:
    def test_rgb_frame_is_kept_as_uint8(self) -> None:
        img = np.arange(2 * 3 * 3, dtype=float).reshape(2, 3, 3) * 10
        disp = _run_with_image(img.tolist())
        frame = disp.latest_frame
        assert frame is not None
        assert frame.dtype == np.uint8
        assert frame.shape == (2, 3, 3)
        np.testing.assert_array_equal(frame, img.astype(np.uint8))

    def test_gray_frame(self) -> None:
        disp = _run_with_image([[0.0, 128.0], [255.0, 64.0]])
        assert disp.latest_frame is not None
        assert disp.latest_frame.shape == (2, 2)

    @pytest.mark.parametrize(
        ("value", "shape_text"),
        [
            ([1.0, 2.0], "(2,)"),
            ([[[1.0, 2.0], [3.0, 4.0]]], "(1, 2, 2)"),
        ],
    )
    def test_non_image_shapes_are_rejected_before_running(
        self, value: object, shape_text: str
    ) -> None:
        with pytest.raises(BlockSpecError, match=r"\(H, W\) or \(H, W, 3\)") as info:
            _run_with_image(value)
        assert shape_text in str(info.value)

    def test_too_many_pixels_is_rejected(self) -> None:
        block = ImageDisplay(id="big")
        with pytest.raises(BlockSpecError, match="exceeds the limit"):
            block._apply_input_shapes(((1081, 1920, 3),))
        block._apply_input_shapes(((1080, 1920, 3),))  # ちょうど上限は通る

    def test_scalar_input_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="scalar signal"):
            _run_with_image(1.0)


class TestValueMapping:
    def test_vmax_scales_and_clips(self) -> None:
        disp = _run_with_image([[0.0, 0.5], [1.0, 2.0]], vmax=1.0)
        assert disp.latest_frame is not None
        np.testing.assert_array_equal(disp.latest_frame, [[0, 128], [255, 255]])

    def test_negative_values_clip_to_zero(self) -> None:
        disp = _run_with_image([[-5.0, 10.0]])
        assert disp.latest_frame is not None
        np.testing.assert_array_equal(disp.latest_frame, [[0, 10]])

    def test_nan_becomes_zero_and_inf_becomes_max(self) -> None:
        block = ImageDisplay(id="d")
        block.record_v(0.0, (np.array([[np.nan, np.inf, -np.inf]]),))
        assert block.latest_frame is not None
        np.testing.assert_array_equal(block.latest_frame, [[0, 255, 0]])

    @pytest.mark.parametrize("vmax", [0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_vmax(self, vmax: float) -> None:
        with pytest.raises(BlockSpecError, match="vmax"):
            ImageDisplay(vmax=vmax)


class TestLatestFrameOnly:
    def test_keeps_only_latest_frame_and_counts(self) -> None:
        block = ImageDisplay(id="d")
        assert block.latest_frame is None
        assert block.frame_time is None
        block.record_v(0.0, (np.zeros((2, 2)),))
        block.record_v(0.5, (np.full((2, 2), 7.0),))
        assert block.frame_count == 2
        assert block.frame_time == 0.5
        assert block.latest_frame is not None
        assert int(block.latest_frame[0, 0]) == 7

    def test_reset_clears(self) -> None:
        block = ImageDisplay(id="d")
        block.record_v(0.0, (np.zeros((2, 2)),))
        block.reset()
        assert block.latest_frame is None
        assert block.frame_time is None
        assert block.frame_count == 0

    def test_run_records_every_base_step(self) -> None:
        disp = _run_with_image([[1.0]], t_end=0.5)
        assert disp.frame_count == 6  # t = 0, 0.1, ..., 0.5
        assert disp.frame_time == pytest.approx(0.5)

    def test_not_treated_as_scope(self) -> None:
        """Scope 系の duck-type 名を持たない (= scope_batch 経路に乗らない、ADR-0082 §(1))。"""
        block = ImageDisplay()
        for attr in ("times", "values", "labels"):
            assert not hasattr(block, attr)


class TestPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.1)
        sim.add(Constant(value=[[1.0]], id="src"))
        sim.add(ImageDisplay(vmax=2.0, id="disp"))
        sim.connect("src", "disp")
        path = tmp_path / "m.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        disp_entry = next(b for b in data["blocks"] if b["id"] == "disp")
        assert disp_entry["type"] == "flode.blocks.sinks.ImageDisplay"
        assert disp_entry["params"] == {"vmax": 2.0}
        loaded = Simulator.load(path)
        disp = loaded.get_block("disp")
        assert isinstance(disp, ImageDisplay)
        assert disp.vmax == 2.0


class TestPlot:
    def test_plot_draws_latest_frame(self) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        block = ImageDisplay(id="d")
        block.record_v(0.0, (np.zeros((2, 3, 3)),))
        ax = block.plot()
        assert len(ax.images) == 1
        plt.close(ax.figure)
