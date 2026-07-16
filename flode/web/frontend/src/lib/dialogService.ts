// v0.32.0: Promise ベースの dialog service。
//
// window.alert / window.confirm / window.prompt はブラウザネイティブのモーダル
// (= chrome の素朴な dialog) を出すが、デスクトップアプリ風 UI と整合しない
// ため独自モーダルに置換する (= ADR §UI design system 準拠)。
//
// API:
//   await dialog.alert("Cleaned 5 files.");
//   const ok = await dialog.confirm("Delete 5 items?", { variant: "danger" });
//   const name = await dialog.prompt("New folder name:", { defaultValue: "" });
//
// 設計:
//   - module-level singleton: React component 外 (= commands.ts 等) からも呼べる
//   - 同時に複数 dialog を出さない (= queue で順次表示)
//   - DialogHost component が `subscribe` で active を購読、Portal で render
//   - `resolveCurrent(value)` で active を閉じて次の queue を pop

export type DialogKind = "alert" | "confirm" | "prompt";

export interface AlertOptions {
  /** Title bar に表示する文字列。既定値は呼出し側 (= DialogHost) で i18n。 */
  title?: string;
  /** OK ボタンの label。既定値 = "OK"。 */
  okLabel?: string;
}

export interface ConfirmOptions {
  title?: string;
  okLabel?: string;
  cancelLabel?: string;
  /** "danger" = OK ボタンを赤系 (= 削除など破壊系操作)。既定は "primary"。 */
  variant?: "primary" | "danger";
}

export interface PromptOptions {
  title?: string;
  /** 初期値。空文字なら placeholder のみ表示。 */
  defaultValue?: string;
  /** input の placeholder。 */
  placeholder?: string;
  okLabel?: string;
  cancelLabel?: string;
}

/**
 * 内部 representation。各 dialog は Promise の resolve を握る。
 * close 時に resolve(value) して queue から次へ進む。
 */
export interface PendingDialog {
  kind: DialogKind;
  message: string;
  options: AlertOptions | ConfirmOptions | PromptOptions;
  // resolve の型は kind に応じて void / boolean / (string | null)
  resolve: (value: unknown) => void;
}

// ---------------------------------------------------------------------------
// Singleton state
// ---------------------------------------------------------------------------

let _current: PendingDialog | null = null;
const _queue: PendingDialog[] = [];
const _listeners = new Set<() => void>();

function _notify(): void {
  _listeners.forEach((l) => l());
}

function _enqueue(req: PendingDialog): void {
  if (_current === null) {
    _current = req;
    _notify();
  } else {
    _queue.push(req);
  }
}

/** Active dialog を取得 (= DialogHost が render する対象)。 */
export function getCurrentDialog(): PendingDialog | null {
  return _current;
}

/** Active dialog の更新を購読する (= DialogHost の useSyncExternalStore 用)。 */
export function subscribeDialog(listener: () => void): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}

/**
 * Active dialog を resolve して閉じ、queue から次へ進む。
 * `value` の型は呼出し時の dialog kind に依存:
 * - alert: undefined
 * - confirm: boolean (= true で OK、false で Cancel)
 * - prompt: string | null (= 文字列で OK、null で Cancel)
 */
export function resolveCurrentDialog(value: unknown): void {
  if (_current === null) return;
  const resolve = _current.resolve;
  _current = _queue.shift() ?? null;
  _notify();
  resolve(value);
}

/** test 用: queue / current / listeners をクリアする。production では使わない。 */
export function _resetDialogServiceForTest(): void {
  // pending の Promise は reject せず garbage collect 任せ (= test 専用)
  _current = null;
  _queue.length = 0;
  _listeners.clear();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const dialog = {
  /**
   * 情報 alert (1-button OK)。``window.alert`` の置換。
   * Promise は OK 押下 / Escape / 外側クリックで resolve(void)。
   */
  alert(message: string, options: AlertOptions = {}): Promise<void> {
    return new Promise<void>((resolve) => {
      _enqueue({
        kind: "alert",
        message,
        options,
        resolve: () => resolve(),
      });
    });
  },

  /**
   * 確認 confirm (Cancel / OK)。``window.confirm`` の置換。
   * Promise は OK で true、Cancel / Escape / 外側クリックで false。
   */
  confirm(message: string, options: ConfirmOptions = {}): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      _enqueue({
        kind: "confirm",
        message,
        options,
        resolve: (v) => resolve(Boolean(v)),
      });
    });
  },

  /**
   * 入力 prompt (text input + Cancel / OK)。``window.prompt`` の置換。
   * Promise は OK で入力文字列、Cancel / Escape / 外側クリックで null。
   */
  prompt(message: string, options: PromptOptions = {}): Promise<string | null> {
    return new Promise<string | null>((resolve) => {
      _enqueue({
        kind: "prompt",
        message,
        options,
        resolve: (v) => resolve(v as string | null),
      });
    });
  },
};
