// ADR-0083 §(4): 音声出力ブロック (AudioOutput) の音をブラウザで鳴らす。
//
// WS ``audio_chunk`` は実時間同期の実行中にだけ届く (サーバ側で保証)。塊ごとに
// AudioBuffer を作り、ブロックごとの「次に鳴らし始める時刻」に詰めて予約する
// (= 途切れずに順に鳴る)。届くのが遅れて予約時刻を過ぎていたら、今から少し先に
// 取り直す (遅れを溜め込まない)。
//
// 音の塊は毎ステップ届くので Zustand の state には載せない (再描画を煽らない)。
// ブロック面の音量計と消音チェックは ``subscribe`` / ``getSnapshot`` で読む。

import type { AudioChunk } from "../types/api";

/** 最初の塊 / 遅れから復帰したときに置く先読み [s] (ネットワークの揺れを吸収)。 */
export const AUDIO_START_LATENCY_S = 0.1;
const INT16_SCALE = 32768;
/** サーバの ``AudioOutput`` が受け付ける範囲 (``flode.blocks.sinks`` の定数と同じ)。 */
const AUDIO_MIN_SAMPLE_RATE = 8000;
const AUDIO_MAX_SAMPLE_RATE = 96000;
const AUDIO_MAX_CHANNELS = 2;

/** ブロックごとの表示用の状態 (音量計・消音)。 */
export interface AudioBlockState {
  /** 直近の塊の RMS (0..1)。 */
  level: number;
  muted: boolean;
}

const _SILENT: AudioBlockState = { level: 0, muted: false };

/** WebAudio のうち、このモジュールが使う部分 (テストで差し替える)。 */
export interface AudioContextLike {
  readonly currentTime: number;
  readonly state: string;
  readonly destination: AudioNode;
  resume(): Promise<void>;
  createBuffer(channels: number, length: number, sampleRate: number): AudioBuffer;
  createBufferSource(): AudioBufferSourceNode;
}

/**
 * base64 の int16 (チャンネル交互) を、チャンネルごとの -1..1 の Float32Array に分ける。
 * 壊れた入力 (長さがチャンネル数で割り切れない等) は余りを捨てる。
 */
export function decodeAudioChunk(chunk: AudioChunk): Float32Array[] {
  const channels = Math.min(AUDIO_MAX_CHANNELS, Math.max(1, Math.floor(chunk.channels)));
  let bytes: Uint8Array;
  try {
    const bin = atob(chunk.data);
    bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  } catch {
    return [];
  }
  const view = new DataView(bytes.buffer);
  const frames = Math.floor(bytes.length / 2 / channels);
  const out = Array.from({ length: channels }, () => new Float32Array(frames));
  for (let f = 0; f < frames; f++) {
    for (let c = 0; c < channels; c++) {
      out[c][f] = view.getInt16((f * channels + c) * 2, true) / INT16_SCALE;
    }
  }
  return out;
}

function rms(channels: Float32Array[]): number {
  let sum = 0;
  let n = 0;
  for (const ch of channels) {
    for (const v of ch) sum += v * v;
    n += ch.length;
  }
  return n === 0 ? 0 : Math.sqrt(sum / n);
}

/** 音声出力ブロックの再生器 (アプリ内で 1 つ)。 */
export class AudioPlayer {
  private ctx: AudioContextLike | null = null;
  private readonly nextStart = new Map<string, number>();
  /** ブロックごとの予約済み (鳴っている / これから鳴る) 音。 */
  private readonly sources = new Map<string, Set<AudioBufferSourceNode>>();
  private readonly states = new Map<string, AudioBlockState>();
  private readonly listeners = new Set<() => void>();

  constructor(private readonly makeContext: () => AudioContextLike | null) {}

  /** 塊を予約する。消音中のブロックは音量計だけ更新する。 */
  enqueue(chunk: AudioChunk): void {
    // サーバが範囲を保証しているが、壊れた塊で WebAudio が例外を投げないよう確かめる
    if (
      !Number.isInteger(chunk.channels) ||
      chunk.channels < 1 ||
      chunk.channels > AUDIO_MAX_CHANNELS ||
      !(chunk.sample_rate >= AUDIO_MIN_SAMPLE_RATE && chunk.sample_rate <= AUDIO_MAX_SAMPLE_RATE)
    ) {
      return;
    }
    const channels = decodeAudioChunk(chunk);
    const frames = channels[0]?.length ?? 0;
    const prev = this.states.get(chunk.block_id) ?? _SILENT;
    this.setState(chunk.block_id, { ...prev, level: rms(channels) });
    if (frames === 0 || prev.muted) return;
    const ctx = this.context();
    if (ctx === null) return;
    // 自動再生の制限で再開できなくても未処理の reject にしない (次の塊で再試行)
    if (ctx.state === "suspended") ctx.resume().catch(() => undefined);
    let source: AudioBufferSourceNode;
    try {
      const buffer = ctx.createBuffer(channels.length, frames, chunk.sample_rate);
      channels.forEach((data, c) => buffer.getChannelData(c).set(data));
      source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
    } catch {
      return;
    }
    const earliest = ctx.currentTime + AUDIO_START_LATENCY_S;
    const planned = this.nextStart.get(chunk.block_id);
    // 予約時刻を過ぎていたら (初回 / 遅延) 今から少し先に取り直す
    const startAt = planned === undefined || planned < ctx.currentTime ? earliest : planned;
    source.start(startAt);
    this.nextStart.set(chunk.block_id, startAt + frames / chunk.sample_rate);
    let set = this.sources.get(chunk.block_id);
    if (set === undefined) {
      set = new Set();
      this.sources.set(chunk.block_id, set);
    }
    const owned = set;
    owned.add(source);
    source.onended = () => owned.delete(source);
  }

  /** 予約済みの音を止め、時刻の予約と音量計を初期化する (実行開始・停止時)。 */
  stopAll(): void {
    for (const id of [...this.sources.keys()]) this.stopBlock(id);
    this.nextStart.clear();
    for (const [id, st] of this.states) this.setState(id, { ...st, level: 0 });
  }

  /** ブロックの消音を切り替える。消音にしたら予約済みの音もその場で止める。 */
  setMuted(blockId: string, muted: boolean): void {
    const prev = this.states.get(blockId) ?? _SILENT;
    this.setState(blockId, { ...prev, muted });
    if (muted) this.stopBlock(blockId);
  }

  private stopBlock(blockId: string): void {
    for (const s of this.sources.get(blockId) ?? []) {
      try {
        s.stop();
      } catch {
        // 既に止まっている
      }
    }
    this.sources.delete(blockId);
    this.nextStart.delete(blockId);
  }

  /** 表示用の状態を返す (``useSyncExternalStore`` の getSnapshot)。 */
  getState(blockId: string): AudioBlockState {
    return this.states.get(blockId) ?? _SILENT;
  }

  /** 状態の変化を購読する (``useSyncExternalStore`` の subscribe)。 */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private setState(blockId: string, next: AudioBlockState): void {
    const prev = this.states.get(blockId);
    if (prev && prev.level === next.level && prev.muted === next.muted) return;
    this.states.set(blockId, next);
    for (const l of this.listeners) l();
  }

  private context(): AudioContextLike | null {
    if (this.ctx === null) this.ctx = this.makeContext();
    return this.ctx;
  }
}

function browserContext(): AudioContextLike | null {
  if (typeof window === "undefined" || typeof window.AudioContext !== "function") return null;
  return new window.AudioContext();
}

/** アプリ全体で共有する再生器。 */
export const audioPlayer = new AudioPlayer(browserContext);
