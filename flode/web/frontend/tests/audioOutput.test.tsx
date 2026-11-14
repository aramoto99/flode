// ADR-0083 §(4) / §(5): 音声出力ブロック (再生器・ブロック面) と実行ログの一覧。

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AudioOutputLive } from "../src/components/BlockNodeView";
import { ErrorView } from "../src/components/ErrorView";
import {
  AUDIO_START_LATENCY_S,
  AudioPlayer,
  audioPlayer,
  decodeAudioChunk,
  type AudioContextLike,
} from "../src/lib/audioPlayer";
import { RUN_LOG_MAX_ENTRIES, useAppStore } from "../src/store/appStore";
import type { AudioChunk, FlwModel, RunLogEntry } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

/** int16 列 (チャンネル交互) を little-endian の base64 にする。 */
function pcm(values: number[]): string {
  const buf = new DataView(new ArrayBuffer(values.length * 2));
  values.forEach((v, i) => buf.setInt16(i * 2, v, true));
  return btoa(String.fromCharCode(...new Uint8Array(buf.buffer)));
}

/** テストの塊のサンプリング周波数 (4 サンプル = 0.5 ms)。 */
const RATE = 8000;
const CHUNK_S = 4 / RATE;

function chunk(overrides: Partial<AudioChunk> = {}): AudioChunk {
  return {
    block_id: "spk",
    t: 0,
    sample_rate: RATE,
    channels: 1,
    data: pcm([0, 16384, -16384, 32767]),
    ...overrides,
  };
}

/** 予約された開始時刻を記録する偽の AudioContext。 */
function fakeContext(now = 10): { ctx: AudioContextLike; starts: number[]; stops: number } {
  const starts: number[] = [];
  const rec = { stops: 0 };
  const ctx = {
    currentTime: now,
    state: "running",
    destination: {} as AudioNode,
    resume: () => Promise.resolve(),
    createBuffer: (channels: number, length: number) => {
      const data = Array.from({ length: channels }, () => new Float32Array(length));
      return { getChannelData: (c: number) => data[c] } as unknown as AudioBuffer;
    },
    createBufferSource: () =>
      ({
        buffer: null,
        connect: () => undefined,
        start: (at: number) => starts.push(at),
        stop: () => {
          rec.stops += 1;
        },
        onended: null,
      }) as unknown as AudioBufferSourceNode,
  };
  return {
    ctx,
    starts,
    get stops() {
      return rec.stops;
    },
  };
}

describe("decodeAudioChunk", () => {
  it("splits interleaved stereo int16 into -1..1 channels", () => {
    const out = decodeAudioChunk(chunk({ channels: 2, data: pcm([16384, -32768, 0, 8192]) }));
    expect(out.map((c) => Array.from(c))).toEqual([
      [0.5, 0],
      [-1, 0.25],
    ]);
  });

  it("returns nothing for invalid base64", () => {
    expect(decodeAudioChunk(chunk({ data: "@@@" }))).toEqual([]);
  });
});

describe("AudioPlayer scheduling", () => {
  it("plays chunks back to back after the start latency", () => {
    const fake = fakeContext(10);
    const player = new AudioPlayer(() => fake.ctx);
    player.enqueue(chunk());
    player.enqueue(chunk());
    expect(fake.starts).toEqual([
      10 + AUDIO_START_LATENCY_S,
      10 + AUDIO_START_LATENCY_S + CHUNK_S,
    ]);
  });

  it("reschedules from now when the plan has fallen behind", () => {
    const fake = fakeContext(10);
    const player = new AudioPlayer(() => fake.ctx);
    player.enqueue(chunk());
    (fake.ctx as { currentTime: number }).currentTime = 50;
    player.enqueue(chunk());
    expect(fake.starts[1]).toBe(50 + AUDIO_START_LATENCY_S);
  });

  it("muted blocks update the meter but schedule nothing", () => {
    const fake = fakeContext();
    const player = new AudioPlayer(() => fake.ctx);
    player.setMuted("spk", true);
    player.enqueue(chunk());
    expect(fake.starts).toEqual([]);
    expect(player.getState("spk").level).toBeGreaterThan(0);
  });

  it("muting stops the block's scheduled sources", () => {
    const fake = fakeContext(10);
    const player = new AudioPlayer(() => fake.ctx);
    player.enqueue(chunk());
    player.enqueue(chunk({ block_id: "other" }));
    player.setMuted("spk", true);
    expect(fake.stops).toBe(1); // "other" は鳴り続ける
  });

  it.each([
    ["too many channels", { channels: 3 }],
    ["sample rate out of range", { sample_rate: 4 }],
  ])("ignores a malformed chunk (%s)", (_label, overrides) => {
    const fake = fakeContext();
    const player = new AudioPlayer(() => fake.ctx);
    player.enqueue(chunk(overrides));
    expect(fake.starts).toEqual([]);
  });

  it("stopAll stops scheduled sources and resets the plan", () => {
    const fake = fakeContext(10);
    const player = new AudioPlayer(() => fake.ctx);
    player.enqueue(chunk());
    player.stopAll();
    expect(fake.stops).toBe(1);
    expect(player.getState("spk").level).toBe(0);
    player.enqueue(chunk());
    expect(fake.starts[1]).toBe(10 + AUDIO_START_LATENCY_S);
  });

  it("does nothing without WebAudio", () => {
    const player = new AudioPlayer(() => null);
    expect(() => player.enqueue(chunk())).not.toThrow();
  });
});

function model(realtime: boolean): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null, realtime },
    blocks: [],
    connections: [],
    layout: {},
  };
}

describe("AudioOutputLive", () => {
  afterEach(() => {
    cleanup();
    audioPlayer.setMuted("spk", false);
  });

  it("asks for real-time sync when it is off", () => {
    useAppStore.setState({ editingModel: model(false) });
    render(<AudioOutputLive blockId="spk" />);
    expect(screen.getByTestId("audio-output-needs-realtime")).toBeTruthy();
    expect(screen.queryByTestId("audio-output-mute")).toBeNull();
  });

  it("toggles mute on the shared player", () => {
    useAppStore.setState({ editingModel: model(true) });
    render(<AudioOutputLive blockId="spk" />);
    const box = screen.getByTestId("audio-output-mute") as HTMLInputElement;
    expect(box.checked).toBe(false);
    act(() => {
      fireEvent.click(box);
    });
    expect(audioPlayer.getState("spk").muted).toBe(true);
    expect((screen.getByTestId("audio-output-mute") as HTMLInputElement).checked).toBe(true);
  });
});

describe("audio_chunk stream handling", () => {
  it("hands chunks to the player without storing them", () => {
    const spy = vi.spyOn(audioPlayer, "enqueue").mockImplementation(() => undefined);
    try {
      useAppStore.getState().handleStreamMessage({ type: "audio_chunk", ...chunk() });
      expect(spy).toHaveBeenCalledWith(chunk());
    } finally {
      spy.mockRestore();
    }
  });
});

function entry(message: string, level = "INFO"): RunLogEntry {
  return { t: 0.25, level, logger: "flode_ws.vizdoom", message };
}

describe("run log", () => {
  beforeEach(() => {
    useAppStore.setState({ runLogs: [], runLogsDropped: 0, lastFailure: null });
  });
  afterEach(() => cleanup());

  it("appends log messages and clears them on the next run", () => {
    const { handleStreamMessage } = useAppStore.getState();
    handleStreamMessage({ type: "log", ...entry("picked up armor") });
    expect(useAppStore.getState().runLogs).toEqual([entry("picked up armor")]);
    useAppStore.getState().startedSimulation("next");
    expect(useAppStore.getState().runLogs).toEqual([]);
  });

  it("counts entries beyond the cap instead of storing them", () => {
    useAppStore.setState({
      runLogs: Array.from({ length: RUN_LOG_MAX_ENTRIES }, (_, i) => entry(String(i))),
    });
    useAppStore.getState().handleStreamMessage({ type: "log", ...entry("x") });
    expect(useAppStore.getState().runLogs).toHaveLength(RUN_LOG_MAX_ENTRIES);
    expect(useAppStore.getState().runLogsDropped).toBe(1);
  });

  it("is listed in the log tab even without a failure", () => {
    useAppStore.getState().replaceRunLogs([entry("hello"), entry("careful", "WARNING")], 3);
    render(<ErrorView />);
    const list = screen.getByTestId("run-log-list");
    expect(list.textContent).toContain("hello");
    expect(list.textContent).toContain("careful");
    expect(list.textContent).toContain("0.250");
    expect(list.textContent).toContain("log.run_log_dropped");
  });

  it("shows the empty state when there is nothing", () => {
    render(<ErrorView />);
    expect(screen.queryByTestId("run-log-list")).toBeNull();
    expect(screen.getByText("log.empty")).toBeTruthy();
  });
});
