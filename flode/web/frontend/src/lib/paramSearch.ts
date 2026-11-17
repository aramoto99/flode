// ADR-0085 §4-D: ユーザーブロックの引数値検索の要求を制御する純粋なコントローラ (React の外)。
//
// - 入力は 300 ms 止まってから送る (IME の変換中は予約しない。Enter は即時)
// - 1 ダイアログから走る要求は常に 1 本。走っている間の検索語は「次に送る 1 つ」に上書きで溜める
// - 世代番号 (入力・追加後の再検索・閉じるで進む) が送った時点と違う応答は捨てる
// - 409 (サーバの同時実行の上限) は 1 秒後に、そのとき最新の検索語で送り直す
// - 閉じたら AbortController で応答の受信をやめる (サーバのスレッドは止まらない)

import { ApiError } from "../api/client";
import type { ParamSearchResponse, ParamSearchRow } from "../types/api";

/** 入力が止まってから検索を送るまでの待ち時間 (ms)。 */
export const PARAM_SEARCH_DEBOUNCE_MS = 300;
/** 409 (同時実行の上限) のあと再試行するまでの待ち時間 (ms)。 */
export const PARAM_SEARCH_RETRY_MS = 1000;
/** 1 回の検索で求める件数 (サーバの既定と同じ)。 */
export const PARAM_SEARCH_LIMIT = 200;

/** サーバの「同時実行の上限」の HTTP ステータス。 */
const HTTP_CONFLICT = 409;

/** ダイアログに出す検索の状態。 */
export interface ParamSearchViewState {
  /** 最新の検索語の結果を待っている (要求中・順番待ち・再試行待ち)。 */
  pending: boolean;
  /** 最後に受け取った最新世代の結果。検索語が空なら ``null``。 */
  result: ParamSearchResponse | null;
  /** 最新世代の要求の失敗メッセージ (サーバの detail)。 */
  error: string | null;
  /**
   * 表示中の結果の提案 (``value``) が、追加の前の ``current`` に基づく (追加後の再検索の
   * 応答待ち、またはその再検索が失敗した)。この間は選択・追加をさせない (古い提案は
   * 追加済みの名前と衝突しうるため)。
   */
  stale: boolean;
}

/** 検索を送る関数 (``searchParamValues`` を型・引数名で束ねたもの)。 */
export type ParamSearchFn = (
  query: string,
  current: string[],
  signal: AbortSignal,
) => Promise<ParamSearchResponse>;

/** ``ParamSearchController`` の構成。 */
export interface ParamSearchControllerOptions {
  /** 検索要求を送る。 */
  search: ParamSearchFn;
  /**
   * 要求を送る時点の引数の値 (応答待ちの未確定値を含む)。開いた時点で捕まえない。
   * ADR-0086 §3-D: 省略可能 (行エディタの pick の検索は ``current`` を送らない。省略時は空配列)。
   */
  getCurrent?: () => string[];
  /** 状態が変わるたびに呼ばれる。 */
  onState: (state: ParamSearchViewState) => void;
  /** デバウンス (ms)。テスト用。 */
  debounceMs?: number;
  /** 409 の再試行の待ち (ms)。テスト用。 */
  retryMs?: number;
}

/** 走っている要求 (検索語と、送った時点の世代)。 */
interface InFlight {
  query: string;
  generation: number;
  abort: AbortController;
}

/**
 * 失敗した要求のメッセージを取り出す (400 の detail は素の文字列)。
 *
 * @param err - ``search`` が投げた値。
 * @returns 表示用の文字列 (信頼できない文字列。描く側で整形する)。
 */
export function paramSearchErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    return typeof err.rawDetail === "string" && err.rawDetail !== ""
      ? err.rawDetail
      : err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

/**
 * 1 つの検索ダイアログの要求を制御する。
 *
 * 使い方: 入力のたびに ``setQuery``、Enter で ``submit``、追加の後に ``refresh``、
 * 閉じるときに ``dispose``。状態は ``onState`` で受け取る。
 */
export class ParamSearchController {
  private readonly opts: Required<ParamSearchControllerOptions>;
  private latestQuery = "";
  private generation = 0;
  private inFlight: InFlight | null = null;
  private queued: string | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  /** ``request`` 済み (送信・順番待ち・再試行待ちを含む) の最新の世代。 */
  private requestedGeneration = -1;
  private disposed = false;
  private state: ParamSearchViewState = {
    pending: false,
    result: null,
    error: null,
    stale: false,
  };

  constructor(opts: ParamSearchControllerOptions) {
    this.opts = {
      debounceMs: PARAM_SEARCH_DEBOUNCE_MS,
      retryMs: PARAM_SEARCH_RETRY_MS,
      ...opts,
      getCurrent: opts.getCurrent ?? (() => []),
    };
  }

  /**
   * 検索語の入力。変換中でなければ、止まってから ``debounceMs`` 後に送る。
   *
   * @param raw - 入力欄の値 (前後の空白は送るときに除く)。
   * @param composing - IME の変換中なら ``true`` (予約しない。確定後にもう一度呼ぶ)。
   */
  setQuery(raw: string, composing = false): void {
    if (this.disposed) return;
    const query = raw.trim();
    const changed = query !== this.latestQuery;
    // 検索語が (trim 後に) 変わらず、その世代の要求が既に出ている (結果・要求中・順番待ち・
    // 再試行待ち・失敗のいずれか) なら送り直さない。明示的な再検索は Enter (submit)
    if (!changed && this.debounceTimer === null && this.requestedGeneration === this.generation) {
      return;
    }
    this.clearDebounce();
    if (changed) {
      this.latestQuery = query;
      this.generation += 1;
      this.clearRetry();
    }
    if (query === "") {
      this.clearToIdle();
      return;
    }
    if (composing) return;
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.request();
    }, this.opts.debounceMs);
  }

  /**
   * Enter: 待たずに最新の検索語で送る。
   *
   * @param raw - 入力欄の値。
   */
  submit(raw: string): void {
    if (this.disposed) return;
    this.setQuery(raw);
    this.clearDebounce();
    if (this.latestQuery !== "") this.request();
  }

  /** 追加の後: 同じ検索語で検索し直す (``current`` が変わり、ブロックの提案が変わるため)。 */
  refresh(): void {
    if (this.disposed || this.latestQuery === "") return;
    this.clearDebounce();
    this.clearRetry();
    this.generation += 1;
    this.update({ stale: this.state.result !== null });
    this.request();
  }

  /** 閉じる: 以後の応答を捨て、受信をやめ、タイマーを止める。 */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.generation += 1;
    this.clearDebounce();
    this.clearRetry();
    this.queued = null;
    this.inFlight?.abort.abort();
  }

  /** 最新の検索語を送る (走っている要求があれば順番待ちに上書きする)。 */
  private request(): void {
    const query = this.latestQuery;
    if (query === "") return;
    this.requestedGeneration = this.generation;
    const running = this.inFlight;
    if (running !== null) {
      // 同じ世代の同じ検索語が既に走っているなら送り直さない
      if (running.generation === this.generation && running.query === query) {
        this.queued = null;
      } else {
        this.queued = query;
      }
      this.update({ pending: true });
      return;
    }
    this.send(query);
  }

  private send(query: string): void {
    const generation = this.generation;
    const abort = new AbortController();
    const flight: InFlight = { query, generation, abort };
    this.inFlight = flight;
    // 前の要求の失敗は、新しい要求を送った時点で消す (結果は応答が来るまで残す)
    this.update({ pending: true, error: null });
    let promise: Promise<ParamSearchResponse>;
    try {
      promise = this.opts.search(query, [...this.opts.getCurrent()], abort.signal);
    } catch (err) {
      promise = Promise.reject(err);
    }
    promise.then(
      (result) => this.settle(flight, () =>
          this.update({ pending: false, result, error: null, stale: false }),
        ),
      (err: unknown) =>
        this.settle(flight, () => {
          if (err instanceof ApiError && err.status === HTTP_CONFLICT) {
            this.scheduleRetry(generation);
          } else {
            this.update({ pending: false, error: paramSearchErrorText(err) });
          }
        }),
    );
  }

  /**
   * 応答の後始末。最新世代の応答だけ ``apply`` し、順番待ちがあれば送る。
   */
  private settle(flight: InFlight, apply: () => void): void {
    if (this.inFlight === flight) this.inFlight = null;
    if (this.disposed) return;
    if (flight.generation === this.generation) apply();
    const next = this.queued;
    this.queued = null;
    if (next !== null && this.latestQuery !== "") this.send(this.latestQuery);
  }

  private scheduleRetry(generation: number): void {
    this.clearRetry();
    this.update({ pending: true });
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.disposed || generation !== this.generation) return;
      this.request();
    }, this.opts.retryMs);
  }

  private clearToIdle(): void {
    this.queued = null;
    this.update({ pending: false, result: null, error: null, stale: false });
  }

  private clearDebounce(): void {
    if (this.debounceTimer !== null) clearTimeout(this.debounceTimer);
    this.debounceTimer = null;
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private update(patch: Partial<ParamSearchViewState>): void {
    this.state = { ...this.state, ...patch };
    this.opts.onState(this.state);
  }
}

/**
 * 「追加」の結果の引数の値: 表の並び順で選んだ行の ``value`` を末尾に足す。
 * 既に ``current`` にある値と、選んだ中で重なる値は足さない (SPEC-0036 U-5 / U-6)。
 *
 * @param current - その時点の引数の値。
 * @param rows - 表の行 (表示順)。
 * @param selected - 選ばれた行の ``value``。
 * @returns 新しい値の一覧 (足すものが無ければ ``current`` と同じ内容)。
 */
export function appendUniqueValues(
  current: ReadonlyArray<string>,
  rows: ReadonlyArray<ParamSearchRow>,
  selected: ReadonlySet<string>,
): string[] {
  const seen = new Set(current);
  const out = [...current];
  for (const row of rows) {
    if (!selected.has(row.value) || seen.has(row.value)) continue;
    seen.add(row.value);
    out.push(row.value);
  }
  return out;
}
