// ADR-0086 §3-D (X4): ``POST /api/v1/blocks/param-rows`` の要求をページ全体で 1 本に直列化する
// キュー (React の外の純粋なクラス)。
//
// - 同時に走る要求は 1 本 (サーバの同時実行の上限 2 のうち 1 枠だけを使い、残りは検索
//   ダイアログ・別タブに空ける)
// - 各要求は「スロットキー」を持つ (``describe:<blockId>:<param>`` / ``dialog:<id>:form`` 等)。
//   まだ送っていない要求は、同じスロットの新しい要求で置き換える (最新だけ送る)。送った要求の
//   応答は呼び出し側が世代番号で捨てる
// - 優先度 2 段: ダイアログ由来 (利用者が待っている) を表の describe より先に送る。同じ段は先着順
// - 409 (同時実行の上限) は先頭の要求を 1 秒後に送り直す。待つ間に同じスロットへ新しい要求が
//   来ていればそちらを送り、取り消されたスロットは送らない。回数の上限は設けない
//   (既知の制約: サーバが 409 を返し続けると無限に送り直し、後ろの要求も待ち続ける。
//   ADR-0085 の検索ダイアログの 409 再送と同じ扱い)
// - 取り消しはスロット単位。待ち行列から除き、走っている要求は AbortController で受信をやめる
//   (サーバのスレッドは走り切る)

import { ApiError, paramRows } from "../api/client";
import type { ParamRowsAction, ParamRowsActionMap, ParamRowsRequest } from "../types/api";
import { PARAM_SEARCH_RETRY_MS } from "./paramSearch";

/** サーバの「同時実行の上限」の HTTP ステータス。 */
const HTTP_CONFLICT = 409;

/** 要求の優先度 (``dialog`` が先)。 */
export type ParamRowsPriority = "dialog" | "table";

/**
 * 要求が送られずに終わった (同じスロットの新しい要求に置き換わった / 取り消された)。
 * 呼び出し側は表示を変えずに無視する。
 */
export class ParamRowsCancelledError extends Error {
  /** ``true`` = 同じスロットの新しい要求に置き換わった、``false`` = 取り消された。 */
  readonly superseded: boolean;
  constructor(superseded: boolean) {
    super(superseded ? "superseded by a newer request" : "cancelled");
    this.name = "ParamRowsCancelledError";
    this.superseded = superseded;
  }
}

/**
 * ``err`` がキューによる置き換え・取り消しか。
 *
 * @param err - 要求の失敗値。
 */
export function isParamRowsCancelled(err: unknown): err is ParamRowsCancelledError {
  return err instanceof ParamRowsCancelledError;
}

/** 待ち行列の 1 件。 */
interface Entry {
  slot: string;
  priority: ParamRowsPriority;
  run: (signal: AbortSignal) => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (err: unknown) => void;
}

/** 走っている要求。 */
interface Running {
  entry: Entry;
  abort: AbortController;
}

/** ``ParamRowsQueue`` の構成 (テスト用)。 */
export interface ParamRowsQueueOptions {
  /** 409 の再送までの待ち (ms)。 */
  retryMs?: number;
}

/** ページ全体で 1 本に直列化する要求キュー。 */
export class ParamRowsQueue {
  private readonly retryMs: number;
  private pending: Entry[] = [];
  private running: Running | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: ParamRowsQueueOptions = {}) {
    this.retryMs = opts.retryMs ?? PARAM_SEARCH_RETRY_MS;
  }

  /**
   * 要求を待ち行列に入れる。同じスロットのまだ送っていない要求は置き換える
   * (古い方の Promise は ``ParamRowsCancelledError(superseded)`` で失敗する)。
   *
   * @param slot - スロットキー。
   * @param priority - 優先度。
   * @param run - 要求を送る関数 (受信をやめるための signal を受ける)。
   * @returns 応答 (409 は内部で再送するので返らない)。
   */
  enqueue<T>(
    slot: string,
    priority: ParamRowsPriority,
    run: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const entry: Entry = {
        slot,
        priority,
        run,
        resolve: (v) => resolve(v as T),
        reject,
      };
      const at = this.pending.findIndex((e) => e.slot === slot);
      if (at >= 0) {
        // 先着順の位置はそのままに、中身だけ最新にする
        this.pending[at]!.reject(new ParamRowsCancelledError(true));
        this.pending[at] = entry;
      } else {
        this.pending.push(entry);
      }
      this.pump();
    });
  }

  /**
   * スロットの要求を取り消す (待ち行列から除き、走っていれば受信をやめる)。
   *
   * @param slot - スロットキー。
   */
  cancel(slot: string): void {
    this.cancelWhere((s) => s === slot);
  }

  /**
   * 前置きが一致するスロットの要求をすべて取り消す (ダイアログを閉じたとき等)。
   *
   * @param prefix - スロットキーの前置き (例: ``dialog:3:``)。
   */
  cancelPrefix(prefix: string): void {
    this.cancelWhere((s) => s.startsWith(prefix));
  }

  /** 待ち行列の件数 (走っている要求を含まない。テスト用)。 */
  get pendingCount(): number {
    return this.pending.length;
  }

  /** 走っている要求のスロット (テスト用)。 */
  get runningSlot(): string | null {
    return this.running?.entry.slot ?? null;
  }

  /** すべて取り消してタイマーを止める (テスト用)。 */
  reset(): void {
    this.cancelWhere(() => true);
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private cancelWhere(match: (slot: string) => boolean): void {
    const keep: Entry[] = [];
    for (const e of this.pending) {
      if (match(e.slot)) e.reject(new ParamRowsCancelledError(false));
      else keep.push(e);
    }
    this.pending = keep;
    const running = this.running;
    if (running !== null && match(running.entry.slot)) {
      // 受信をやめて次へ進む (サーバのスレッドは走り切る。遅れて来た応答は捨てる)
      this.running = null;
      running.abort.abort();
      running.entry.reject(new ParamRowsCancelledError(false));
      this.pump();
    }
  }

  /** 走っていなければ、次の要求 (ダイアログ優先・先着順) を送る。 */
  private pump(): void {
    if (this.running !== null || this.retryTimer !== null) return;
    let at = this.pending.findIndex((e) => e.priority === "dialog");
    if (at < 0) at = this.pending.length > 0 ? 0 : -1;
    if (at < 0) return;
    const [entry] = this.pending.splice(at, 1);
    this.send(entry!);
  }

  private send(entry: Entry): void {
    const abort = new AbortController();
    const running: Running = { entry, abort };
    this.running = running;
    let promise: Promise<unknown>;
    try {
      promise = entry.run(abort.signal);
    } catch (err) {
      promise = Promise.reject(err);
    }
    promise.then(
      (value) => {
        if (this.running !== running) return; // 取り消し済み
        this.running = null;
        entry.resolve(value);
        this.pump();
      },
      (err: unknown) => {
        if (this.running !== running) return;
        this.running = null;
        if (err instanceof ApiError && err.status === HTTP_CONFLICT) {
          // 先頭に戻して 1 秒待つ (待つ間に同じスロットの新しい要求が来れば置き換わる)
          this.pending.unshift(entry);
          this.retryTimer = setTimeout(() => {
            this.retryTimer = null;
            this.pump();
          }, this.retryMs);
          return;
        }
        entry.reject(err);
        this.pump();
      },
    );
  }
}

/** ページ全体で共有するキュー。 */
export const paramRowsQueue = new ParamRowsQueue();

/**
 * 行エディタの要求を共有キュー経由で送る。
 *
 * @param slot - スロットキー。
 * @param priority - 優先度。
 * @param req - 要求。
 * @returns 応答。置き換え・取り消しは ``ParamRowsCancelledError`` で失敗する。
 */
export function queueParamRows<A extends ParamRowsAction>(
  slot: string,
  priority: ParamRowsPriority,
  req: ParamRowsRequest<A>,
): Promise<ParamRowsActionMap[A]["res"]> {
  return paramRowsQueue.enqueue(slot, priority, (signal) => paramRows(req, signal));
}
