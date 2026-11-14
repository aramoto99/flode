"""ADR-0083 §(4): 音声出力ブロック AudioOutput と ``audio_chunk`` 配信のテスト。"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block
from flode.blocks import AudioOutput, Constant
from flode.blocks.sinks import AUDIO_MAX_PENDING_SECONDS
from flode.core.simulator import Simulator
from flode.exceptions import BlockSpecError
from flode.server.runtime import SimulationManager, audio_chunk_payload


class TestParams:
    @pytest.mark.parametrize("rate", [7999, 96001, 44100.5, float("inf"), float("nan")])
    def test_bad_sample_rate(self, rate: float) -> None:
        with pytest.raises(BlockSpecError, match="sample_rate"):
            AudioOutput(sample_rate=rate)  # type: ignore[arg-type]

    @pytest.mark.parametrize("scale", [0.0, -1.0, float("nan"), float("inf")])
    def test_bad_scale(self, scale: float) -> None:
        with pytest.raises(BlockSpecError, match="scale"):
            AudioOutput(scale=scale)

    def test_params_round_trip(self) -> None:
        b = AudioOutput(sample_rate=22050, scale=32768.0)
        assert b._params == {"sample_rate": 22050, "scale": 32768.0}


class TestRecord:
    def test_mono_vector_is_scaled_and_clipped(self) -> None:
        b = AudioOutput()
        b.record_v(0.0, (np.array([0.0, 0.5, -1.0, 2.0, np.nan]),))
        out = b.take_pending()
        assert out is not None
        assert out.shape == (5, 1)
        assert out[:, 0].tolist() == [0, 16384, -32767, 32767, 0]
        assert b.take_pending() is None  # 取り出したら空

    def test_stereo_int16_scale(self) -> None:
        b = AudioOutput(scale=32768.0)
        b.record_v(0.0, (np.array([[16384.0, -32768.0]]),))
        out = b.take_pending()
        assert out is not None
        assert out.shape == (1, 2)
        assert b.channels == 2

    def test_scalar_record_is_one_sample(self) -> None:
        b = AudioOutput()
        b.record(0.0, np.array([0.25]))
        b.record(0.1, np.array([-0.25]))
        out = b.take_pending()
        assert out is not None
        assert out[:, 0].tolist() == [8192, -8192]

    @pytest.mark.parametrize("shape", [(4, 3), (2, 2, 2)])
    def test_bad_shape(self, shape: tuple[int, ...]) -> None:
        with pytest.raises(BlockSpecError, match="audio samples"):
            AudioOutput().record_v(0.0, (np.zeros(shape),))

    def test_channel_change_is_rejected(self) -> None:
        b = AudioOutput()
        b.record_v(0.0, (np.zeros(3),))
        with pytest.raises(BlockSpecError, match="channel count changed"):
            b.record_v(0.1, (np.zeros((3, 2)),))

    def test_pending_is_bounded(self) -> None:
        b = AudioOutput(sample_rate=8000)
        chunk = np.zeros(8000)  # 1 秒
        for _ in range(int(AUDIO_MAX_PENDING_SECONDS) + 3):
            b.record_v(0.0, (chunk,))
        out = b.take_pending()
        assert out is not None
        assert out.shape[0] <= AUDIO_MAX_PENDING_SECONDS * 8000
        assert b.dropped_samples == 3 * 8000

    def test_chunk_longer_than_pending_limit_is_rejected(self) -> None:
        b = AudioOutput(sample_rate=8000)
        too_long = int(AUDIO_MAX_PENDING_SECONDS * 8000) + 1
        with pytest.raises(BlockSpecError, match="exceeds"):
            b.record_v(0.0, (np.zeros(too_long),))
        with pytest.raises(BlockSpecError, match="exceeds"):
            b._apply_input_shapes(((too_long, 2),))

    def test_close_warns_about_dropped_samples(self, caplog: pytest.LogCaptureFixture) -> None:
        b = AudioOutput(sample_rate=8000)
        for _ in range(int(AUDIO_MAX_PENDING_SECONDS) + 2):
            b.record_v(0.0, (np.zeros(8000),))
        with caplog.at_level("WARNING", logger="flode.blocks.sinks"):
            b.close()
        assert "dropped 16000 samples" in caplog.text

    def test_reset_clears(self) -> None:
        b = AudioOutput()
        b.record_v(0.0, (np.zeros((2, 2)),))
        b.reset()
        assert b.take_pending() is None
        assert b.channels is None


def test_payload_is_interleaved_little_endian_int16() -> None:
    b = AudioOutput(sample_rate=8000)
    b.record_v(0.0, (np.array([[1.0, -1.0], [0.5, 0.0]]),))
    payload = audio_chunk_payload(b, t=0.2)
    assert payload is not None
    assert payload["sample_rate"] == 8000
    assert payload["channels"] == 2
    data = np.frombuffer(base64.b64decode(payload["data"]), dtype="<i2")
    assert data.tolist() == [32767, -32767, 16384, 0]
    assert audio_chunk_payload(b, t=0.3) is None


class _Chunks(Block):
    """周期 0.1 s で 4 サンプルの塊を出す離散ブロック (基準ステップは 0.05 s)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=0, n_outputs=1, sample_time=0.1, port_shapes_out=((4,),))
        self._params = {}
        self._n = 0

    def output_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.full(4, round(t * 10) / 10.0),)


def _run(realtime: bool) -> list[dict[str, Any]]:
    sim = Simulator(t_end=0.3, dt=0.05, realtime=realtime)
    sim.add(_Chunks(id="src"))
    sim.add(Constant(value=0.0, id="unused"))
    sim.add(AudioOutput(sample_rate=8000, id="spk"))
    sim.connect("src", "spk")

    async def go() -> list[dict[str, Any]]:
        sim_id = manager.start(
            model_id="<inline>", simulator=sim, loop=asyncio.get_running_loop(), scope_batch_size=10
        )
        return [m async for m in manager.stream(sim_id)]

    manager = SimulationManager()
    try:
        return asyncio.run(go())
    finally:
        manager.shutdown()


def test_chunks_are_streamed_once_per_upstream_sample() -> None:
    """基準ステップ (0.05 s) が上流の周期 (0.1 s) より細かくても塊は重複しない。"""
    messages = _run(realtime=True)
    chunks = [m for m in messages if m["type"] == "audio_chunk"]
    samples = np.concatenate(
        [np.frombuffer(base64.b64decode(m["data"]), dtype="<i2") for m in chunks]
    )
    assert samples.shape == (4 * 4,)  # t = 0, 0.1, 0.2, 0.3 の 4 回
    assert messages[-1]["type"] == "completed"


def test_no_audio_without_realtime() -> None:
    messages = _run(realtime=False)
    assert not [m for m in messages if m["type"] == "audio_chunk"]
