"""SPEC-0034 F-6 / ADR-0082 §(1): 画像表示ブロックのコマ配信 (WS ``image_frame`` / results)。"""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flode.blocks import Constant, ImageDisplay
from flode.core.simulator import Simulator
from flode.server import create_app
from flode.server.runtime import (
    IMAGE_FRAME_MAX_BYTES_PER_S,
    IMAGE_FRAME_MIN_INTERVAL_S,
    image_frame_interval,
    image_frame_payload,
)
from flode.server.settings import Settings

_IMG = [[[0.0, 64.0, 128.0], [255.0, 10.0, 20.0]]]  # shape (1, 2, 3)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(workspace_root=tmp_path))
    with TestClient(app) as c:
        yield c


def _seed(workspace: Path, *, t_end: float = 0.5, realtime: bool = False) -> str:
    sim = Simulator(t_end=t_end, dt=0.1, realtime=realtime)
    sim.add(Constant(value=_IMG, id="src"))
    sim.add(ImageDisplay(id="screen"))
    sim.connect("src", "screen")
    sim.save(workspace / "img.flw.json")
    return "img.flw.json"


def _collect(client: TestClient, sim_id: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] in ("completed", "stopped", "failed"):
                return messages


def _decode(frame: dict[str, Any]) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(frame["data"]), dtype=np.uint8)
    return raw.reshape(frame["height"], frame["width"], frame["channels"])


class TestImageFrameStream:
    def test_frames_are_streamed_and_last_one_precedes_terminal(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        path = _seed(tmp_path)
        sim_id = client.post("/api/v1/simulations", json={"model_path": path}).json()[
            "simulation_id"
        ]
        messages = _collect(client, sim_id)
        frames = [m for m in messages if m["type"] == "image_frame"]
        assert frames, "no image_frame received"
        last = frames[-1]
        assert last["block_id"] == "screen"
        assert (last["height"], last["width"], last["channels"]) == (1, 2, 3)
        np.testing.assert_array_equal(_decode(last), np.asarray(_IMG, dtype=np.uint8))
        assert last["t"] == pytest.approx(0.5)
        # 最後のコマは terminal メッセージより前に届く
        assert messages.index(last) < len(messages) - 1
        assert messages[-1]["type"] == "completed"

    def test_frames_are_throttled(self, client: TestClient, tmp_path: Path) -> None:
        """最速実行 (51 ステップが一瞬) では間引かれて、ステップ数よりずっと少ない。"""
        path = _seed(tmp_path, t_end=5.0)
        sim_id = client.post("/api/v1/simulations", json={"model_path": path}).json()[
            "simulation_id"
        ]
        frames = [m for m in _collect(client, sim_id) if m["type"] == "image_frame"]
        assert 1 <= len(frames) < 51
        assert frames[-1]["t"] == pytest.approx(5.0)

    def test_results_include_last_frame(self, client: TestClient, tmp_path: Path) -> None:
        path = _seed(tmp_path)
        sim_id = client.post("/api/v1/simulations", json={"model_path": path}).json()[
            "simulation_id"
        ]
        _collect(client, sim_id)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            response = client.get(f"/api/v1/simulations/{sim_id}/results")
            if response.status_code == 200:
                break
            time.sleep(0.05)
        images = response.json()["images"]
        assert set(images) == {"screen"}
        np.testing.assert_array_equal(_decode(images["screen"]), np.asarray(_IMG, dtype=np.uint8))


class TestPayload:
    def test_none_before_first_frame(self) -> None:
        assert image_frame_payload(ImageDisplay(id="d")) is None

    def test_gray_frame_has_one_channel(self) -> None:
        block = ImageDisplay(id="d")
        block.record_v(0.25, (np.array([[1.0, 2.0, 3.0]]),))
        payload = image_frame_payload(block)
        assert payload is not None
        assert (payload["height"], payload["width"], payload["channels"]) == (1, 3, 1)
        assert base64.b64decode(payload["data"]) == bytes([1, 2, 3])
        assert payload["t"] == 0.25

    def test_small_frames_are_sent_at_30fps(self) -> None:
        block = ImageDisplay(id="d")
        block.record_v(0.0, (np.zeros((120, 160, 3)),))
        assert image_frame_interval(block) == pytest.approx(IMAGE_FRAME_MIN_INTERVAL_S)

    def test_large_frames_are_sent_less_often(self) -> None:
        """配信量の上限を超える大きなコマは送信間隔を延ばす。"""
        block = ImageDisplay(id="d")
        block.record_v(0.0, (np.zeros((1080, 1920, 3)),))
        expected = 1080 * 1920 * 3 / IMAGE_FRAME_MAX_BYTES_PER_S
        assert image_frame_interval(block) == pytest.approx(expected)
        assert expected > IMAGE_FRAME_MIN_INTERVAL_S
