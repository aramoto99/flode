// flode UI design system — "Property Inspector" 風 primitives。
//
// v0.25.0: ScopeSettingsDialog (v0.24.4) で確立した設計を再利用可能 primitives
// として切り出し、ParameterPanel / ModelSettingsModal / 今後の dialogs を統一する。
//
// ## デザイン原則
//
// 1. **ネイティブ widget**: ``<select>`` / ``<input>`` / ``<input type="checkbox">``
//    をそのまま使う。pill button / switch toggle / segmented control は **使わない**
//    (= デスクトップアプリ感を出す)。
// 2. **プロパティグリッド**: 「ラベル (右寄せ 140px) | 値入力 (左寄せ)」の 2 列、
//    行高 22px で密。多階層 (indent) で manual mode の min/max 等を表現。
// 3. **線は 1px slate-400 / 角は 0px (or 1-2px)**: rounded-md は使わない、または
//    最小限に。
// 4. **subtle gradient**: title bar / footer は ``bg-gradient-to-b
//    from-slate-200 to-slate-100`` で window chrome 感。
// 5. **タブ**: 上部 border 無し + active = 白背景 + border-b 無し で「物理的に
//    上面の紙が手前」感。
// 6. **ボタン**:
//    - primary (= 確定系): ``bg-blue-600 text-white`` (枠あり、shadow なし)
//    - secondary (= reset / cancel): ``bg-white text-slate-700`` border あり
//    - 危険系 (= delete): ``bg-rose-600 text-white``
// 7. **section divider**: ``<small uppercase tracking-wider>`` + 横ルール。
//    section の中身は indent しない (= ラベル右寄せ整列で揃える)。
// 8. **背景色 / ダークモード**: 永続的 out-of-scope (memory `feedback_no_dark_mode`)。

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

// ---------------------------------------------------------------------------
// Native widget Tailwind class constants
// ---------------------------------------------------------------------------

/** ネイティブ ``<input>`` (text / number) 用 class。h-5、1px border、no rounded。 */
export const INPUT_CLS =
  "border border-slate-400 bg-white px-1.5 py-0 text-[11px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

/** ネイティブ ``<input>`` (mono font 数値入力) 用 class。 */
export const INPUT_MONO_CLS =
  "border border-slate-400 bg-white px-1.5 py-0 font-mono text-[11px] tabular-nums text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

/** ネイティブ ``<select>`` 用 class。 */
export const SELECT_CLS =
  "border border-slate-400 bg-white px-1 py-0 text-[11px] text-slate-800 focus:border-blue-500 focus:outline-none";

/** チェックボックス用 class (= 標準寸法、accent blue)。 */
export const CHECKBOX_CLS = "h-3.5 w-3.5 cursor-pointer accent-blue-600";

// ---------------------------------------------------------------------------
// Property grid primitives
// ---------------------------------------------------------------------------

/**
 * プロパティグリッド (= label 右寄せ + value 左寄せ) のコンテナ。
 * 行は ``PropertyRow`` を使う。``SectionDivider`` で区切る。
 */
export function PropertyGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}): JSX.Element {
  return <div className={`flex flex-col ${className ?? ""}`}>{children}</div>;
}

/**
 * 「ラベル: 入力」の 1 行。``indent`` で sub-property (= 親モードに依存する
 * 副入力、例: y_mode=manual 時の y_min/y_max) を表現。
 *
 * ``labelAlign``:
 * - ``"right"`` (default): ラベルを固定幅 column 内で右寄せ。colon が縦に揃って
 *   見やすい — **広い modal (480 px〜)** 向け。
 * - ``"left"``: ラベルを左寄せ、入力までの余分なスペースを潰す。**narrow sidebar
 *   (Inspector 280 px)** 向け。labelWidth はラベル column の上限になり、短い
 *   ラベルは natural width で表示される。
 */
export function PropertyRow({
  label,
  children,
  indent = false,
  labelWidth = 140,
  labelAlign = "right",
}: {
  label: string;
  children: React.ReactNode;
  indent?: boolean;
  labelWidth?: number;
  labelAlign?: "left" | "right";
}): JSX.Element {
  return (
    <div className="flex min-h-[22px] items-center gap-2 py-0.5">
      <label
        title={label}
        className={`shrink-0 truncate text-[11px] text-slate-700 ${
          labelAlign === "right" ? "text-right" : "text-left"
        } ${indent ? "pl-3" : ""}`}
        style={{ width: `${labelWidth}px` }}
      >
        {label}:
      </label>
      <div className="flex min-w-0 flex-1 items-center">{children}</div>
    </div>
  );
}

/**
 * ``PropertyRow`` の直下に表示する補足説明 (小さく薄い 1〜2 行のヒント)。
 *
 * 入力 column に揃えてインデントする (= label column 分の空白を左に取る)。
 * 動的に内容が変わる用途 (例: solver method 選択に応じた解説の切替) に使う。
 * ``labelWidth`` は親 ``PropertyRow`` と揃える。
 */
export function PropertyHint({
  text,
  labelWidth = 140,
  testId,
}: {
  text: string;
  labelWidth?: number;
  testId?: string;
}): JSX.Element {
  return (
    <div className="flex items-start gap-2 pb-1">
      <div className="shrink-0" style={{ width: `${labelWidth}px` }} />
      <p
        data-testid={testId}
        className="min-w-0 flex-1 text-[10px] leading-snug text-slate-500"
      >
        {text}
      </p>
    </div>
  );
}

/**
 * セクション見出し (uppercase tracking-wider + 横ルール)。
 * グルーピング用、property row の前に挿入する。
 */
export function SectionDivider({ label }: { label: string }): JSX.Element {
  return (
    <div className="my-1.5 flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-200" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog shell (業界標準ブロック線図ツールの "Configuration Parameters" 風)
// ---------------------------------------------------------------------------

/**
 * ネイティブダイアログ風の modal シェル。
 *
 * - 角は border-radius 無し (or 1-2px、`rounded` Tailwind class は使わない)
 * - title bar / footer に subtle gradient
 * - 外側クリック / Escape で close
 * - ``onClose`` は呼ぶ側が ``isOpen`` 等で制御
 */
export function DialogShell({
  title,
  width = "w-[540px]",
  onClose,
  children,
  footer,
  ariaLabel,
}: {
  title: string;
  width?: string;
  onClose: () => void;
  children: React.ReactNode;
  /** footer 領域。``DialogFooter`` を渡すのが標準。 */
  footer?: React.ReactNode;
  ariaLabel?: string;
}): JSX.Element {
  // ESC で close
  useEffect(() => {
    const h = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30"
      onClick={onClose}
    >
      <div
        className={`${width} border border-slate-400 bg-slate-50 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
      >
        {/* Title bar */}
        <div className="flex items-center justify-between border-b border-slate-400 bg-gradient-to-b from-slate-200 to-slate-100 px-3 py-1">
          <span className="text-[12px] font-semibold text-slate-800">
            {title}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-5 w-5 items-center justify-center text-slate-600 hover:bg-slate-300 hover:text-slate-900"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        {children}

        {/* Footer */}
        {footer}
      </div>
    </div>
  );
}

/** ``DialogShell`` の footer 領域。左寄せ secondary + 右寄せ primary が標準。 */
export function DialogFooter({
  left,
  right,
}: {
  left?: React.ReactNode;
  right?: React.ReactNode;
}): JSX.Element {
  return (
    <div className="flex items-center justify-between border-t border-slate-400 bg-gradient-to-b from-slate-100 to-slate-200 px-3 py-1.5">
      <div className="flex items-center gap-2">{left}</div>
      <div className="flex items-center gap-2">{right}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

/**
 * Primary action button (= OK / Save / Apply 等、確定系)。
 * 青背景 + 白文字 + slate-500 border。``active:bg-blue-800`` で押下感。
 */
export function PrimaryButton({
  children,
  onClick,
  disabled,
  type = "button",
  testId,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  testId?: string;
}): JSX.Element {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={`border border-slate-500 px-4 py-0.5 text-[11px] font-medium text-white ${
        disabled
          ? "cursor-not-allowed bg-slate-400"
          : "bg-blue-600 hover:bg-blue-700 active:bg-blue-800"
      }`}
    >
      {children}
    </button>
  );
}

/**
 * Secondary action button (= Cancel / Reset / 補助系)。
 * 白背景 + slate text、slate-400 border。
 */
export function SecondaryButton({
  children,
  onClick,
  disabled,
  testId,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={`border border-slate-400 px-2.5 py-0.5 text-[11px] ${
        disabled
          ? "cursor-not-allowed bg-slate-100 text-slate-400"
          : "bg-white text-slate-700 hover:bg-slate-50 active:bg-slate-200"
      }`}
    >
      {children}
    </button>
  );
}

/**
 * 危険系 action button (= Delete 等)。red 系で警告。
 */
export function DangerButton({
  children,
  onClick,
  disabled,
  testId,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={`border border-rose-700 px-2.5 py-0.5 text-[11px] font-medium text-white ${
        disabled
          ? "cursor-not-allowed bg-rose-300"
          : "bg-rose-600 hover:bg-rose-700 active:bg-rose-800"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

/**
 * Dialog 内のタブストリップ。``children`` に ``<TabButton>`` を並べる。
 * active = 白背景 + 太字、inactive = 灰色背景。
 */
export function TabBar({
  children,
  label,
}: {
  children: React.ReactNode;
  label?: string;
}): JSX.Element {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex items-end gap-0 border-b border-slate-400 bg-slate-100 pl-2 pt-1"
    >
      {children}
    </div>
  );
}

export function TabButton({
  active,
  onClick,
  indicator = "none",
  children,
}: {
  active: boolean;
  onClick: () => void;
  /** ADR-0056 §F-2: ``"dot"`` で右上に小さな赤丸を表示 (= Error tab 失敗通知用)。 */
  indicator?: "dot" | "none";
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`-mb-px inline-flex items-center border border-b-0 px-3 py-0.5 text-[11px] ${
        active
          ? "border-slate-400 bg-white text-slate-800 font-medium"
          : "border-transparent bg-slate-100 text-slate-600 hover:text-slate-800"
      }`}
    >
      {children}
      {indicator === "dot" && (
        <span
          aria-hidden="true"
          className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-rose-500"
        />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Common input helpers
// ---------------------------------------------------------------------------

/** 浮動小数 / 整数の入力 (text + inputMode="decimal")。空文字で ``undefined``。 */
export function NumberInput({
  value,
  onChange,
  onBlur,
  testId,
  ariaLabel,
  widthClass = "w-24",
}: {
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  onBlur?: () => void;
  testId?: string;
  ariaLabel?: string;
  widthClass?: string;
}): JSX.Element {
  return (
    <input
      type="text"
      inputMode="decimal"
      value={value === undefined ? "" : String(value)}
      onChange={(e) => {
        const v = e.target.value.trim();
        if (v === "") return onChange(undefined);
        const n = Number(v);
        if (Number.isFinite(n)) onChange(n);
      }}
      onBlur={onBlur}
      data-testid={testId}
      aria-label={ariaLabel}
      className={`${INPUT_MONO_CLS} ${widthClass}`}
    />
  );
}

/** 文字列入力。 */
export function TextInput({
  value,
  onChange,
  onBlur,
  testId,
  ariaLabel,
  widthClass = "w-32",
  mono = false,
}: {
  value: string;
  onChange: (v: string) => void;
  onBlur?: () => void;
  testId?: string;
  ariaLabel?: string;
  widthClass?: string;
  mono?: boolean;
}): JSX.Element {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      data-testid={testId}
      aria-label={ariaLabel}
      className={`${mono ? INPUT_MONO_CLS : INPUT_CLS} ${widthClass}`}
    />
  );
}

// ---------------------------------------------------------------------------
// SPEC-0011 (v5.4.0): Array & expression editor primitives
// ---------------------------------------------------------------------------
//
// 既存の NumberInput / TextInput が `<input>` ベースなのに対し、本セクションの
// primitive は `<textarea>` ベース。配列・長文字列を Inspector で直接編集
// できるようにする。
//
// 検証ポリシー: JsonArrayEditor は blur 時に JSON.parse + 要素型チェックを行い、
// 失敗時は textarea 直下に inline error 表示する (commit しない、既存
// NumberInput が空文字列で commit しないのと同方針)。
// ExpressionEditor は検証なし (block `__init__` 側で構文 reject、ADR-0053
// 寛容方針)。

interface JsonArrayEditorProps {
  value: unknown[];
  onCommit: (next: unknown[]) => void;
  /** ``"number"`` / ``"string"`` は 1-D 配列、``"nested"`` は n-D 数値配列 (SPEC-0018)。 */
  elementType: "number" | "string" | "nested";
  testid?: string;
  placeholder?: string;
  disabled?: boolean;
  widthClass?: string;
}

/** ``"nested"`` mode の検証: n-D 数値配列 (regular shape、全要素 number)。 */
function isNestedNumericArray(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (!Array.isArray(value)) return false;
  if (value.length === 0) return true;
  const first = value[0];
  if (typeof first === "number") {
    return value.every((v) => typeof v === "number" && Number.isFinite(v));
  }
  if (Array.isArray(first)) {
    const firstLen = first.length;
    return value.every(
      (row) =>
        Array.isArray(row) &&
        row.length === firstLen &&
        isNestedNumericArray(row),
    );
  }
  return false;
}

/**
 * 1-D 配列を JSON textarea で編集する primitive (SPEC-0011 §1.1)。
 *
 * 編集中は内部 draft state を持ち、blur 時に JSON.parse + Array.isArray +
 * 要素型一致を検証する。検証 OK なら `onCommit(parsed)`、NG なら textarea 直下に
 * inline error 表示 + commit しない。
 *
 * @example
 *   <JsonArrayEditor
 *     value={[0.0, 1.0, 2.0]}
 *     elementType="number"
 *     onCommit={(next) => updateBlock("breakpoints", next)}
 *   />
 */
export function JsonArrayEditor({
  value,
  onCommit,
  elementType,
  testid,
  placeholder,
  disabled = false,
  widthClass = "min-w-0 flex-1 max-w-[220px]",
}: JsonArrayEditorProps): JSX.Element {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<string>(() => JSON.stringify(value));
  const [error, setError] = useState<string | null>(null);

  // value を canonical JSON で memo 化することで、useEffect の依存配列に
  // 関数呼び出し結果を直接渡す形 (ESLint 警告 + 毎 render stringify) を回避する。
  // 親が参照のみ変えて内容が同じケース (= re-render only) では draft を触らない。
  const canonical = useMemo(() => JSON.stringify(value), [value]);
  useEffect(() => {
    setDraft((prev) => (prev === canonical ? prev : canonical));
    setError(null);
  }, [canonical]);

  const handleBlur = (): void => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft);
    } catch (e) {
      setError(
        t("inspector.array.parse_error", {
          message: (e as Error).message,
        }),
      );
      return;
    }
    if (!Array.isArray(parsed)) {
      setError(t("inspector.array.not_array"));
      return;
    }
    let elementOK: boolean;
    if (elementType === "number") {
      elementOK = parsed.every(
        (x) => typeof x === "number" && Number.isFinite(x),
      );
    } else if (elementType === "string") {
      elementOK = parsed.every((x) => typeof x === "string");
    } else {
      // "nested": n-D 数値配列 (SPEC-0018)、regular shape を再帰検証
      elementOK = isNestedNumericArray(parsed);
    }
    if (!elementOK) {
      setError(
        t("inspector.array.element_type", { expected: elementType }),
      );
      return;
    }
    setError(null);
    onCommit(parsed);
  };

  const rows = Math.max(2, draft.split("\n").length);

  return (
    <div className={`flex flex-col ${widthClass}`}>
      <textarea
        value={draft}
        rows={rows}
        spellCheck={false}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleBlur}
        data-testid={testid}
        aria-label={testid}
        aria-invalid={error !== null}
        className={`${INPUT_MONO_CLS} w-full resize-y`}
      />
      {error !== null && (
        <div
          role="alert"
          data-testid={testid ? `${testid}-error` : undefined}
          className="mt-0.5 text-[10px] text-rose-700"
        >
          {error}
        </div>
      )}
    </div>
  );
}

interface ExpressionEditorProps {
  value: string;
  onCommit: (next: string) => void;
  testid?: string;
  placeholder?: string;
  disabled?: boolean;
  widthClass?: string;
  maxRows?: number;
}

/**
 * 長文字列 (Fcn.expression 等) を多行 textarea で編集する primitive
 * (SPEC-0011 §1.2)。
 *
 * monospace、auto-resize (min 2 / max `maxRows` 行、default 8)。検証は
 * 行わず、blur 時に raw draft を `onCommit` に渡す。構文 reject は block
 * `__init__` 側で行われ Run 時に構造化エラーとして表示される。
 *
 * @example
 *   <ExpressionEditor
 *     value="u[0]**2 + sin(t)"
 *     onCommit={(next) => updateBlock("expression", next)}
 *   />
 */
export function ExpressionEditor({
  value,
  onCommit,
  testid,
  placeholder,
  disabled = false,
  widthClass = "min-w-0 flex-1 max-w-[220px]",
  maxRows = 8,
}: ExpressionEditorProps): JSX.Element {
  const [draft, setDraft] = useState<string>(value);

  // value が外部から変わった場合 (model load 等) は draft を同期する。
  useEffect(() => {
    setDraft((prev) => (prev === value ? prev : value));
  }, [value]);

  const rows = Math.max(2, Math.min(maxRows, draft.split("\n").length));

  return (
    <textarea
      value={draft}
      rows={rows}
      spellCheck={false}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => onCommit(draft)}
      data-testid={testid}
      aria-label={testid}
      className={`${INPUT_MONO_CLS} resize-y ${widthClass}`}
    />
  );
}

// ---------------------------------------------------------------------------
// GridEditor (SPEC-0017 / ADR-0064)
// ---------------------------------------------------------------------------
//
// 2-D 数値配列 (= LookupTable2D の table) を Property Inspector 風スタイルで
// 編集する primitive。SPEC-0018 (n-D Lookup) / SPEC-0019 (Prelookup) で再利用
// 予定。
//
// 設計判断:
// - 各セルは ``<input type="number">`` + ``INPUT_MONO_CLS`` (NumberInput と
//   同じ class)。onBlur で commit。
// - 行/列追加は ``[+ Row]`` / ``[+ Col]`` の SecondaryButton (右クリックメニュー
//   不採用 — discoverability 優先、ADR-0064 §C-1)。
// - 行/列削除は header の hover 表示 ``[×]`` ボタン (確認 dialog なし)。
// - shape link: ``rowCountLink`` / ``colCountLink`` で breakpoints の長さと
//   shape の整合性を表示。不一致時は ! 警告。
// - 50×50 を超えると上部に警告メッセージ (実用上限指針)。
// - ``[JSON ▼]`` トグルで JsonArrayEditor (2-D 配列) にフォールバック。

const GRID_WARNING_THRESHOLD = 50;

interface GridEditorProps {
  /** 2-D 数値配列。jagged は呼び出し側で防ぐ前提 (= 構築時 validate)。 */
  value: number[][];
  /** commit 時のコールバック (cell edit / row|col add|remove / JSON mode commit)。 */
  onChange: (next: number[][]) => void;
  /** 行ラベル (省略時は ``r[i]``)。 */
  rowLabels?: string[];
  /** 列ラベル (省略時は ``c[j]``)。 */
  colLabels?: string[];
  /** breakpoints_row.length。表示の shape 整合性チェック用。 */
  rowCountLink?: number;
  /** breakpoints_col.length。同上。 */
  colCountLink?: number;
  /** disable 全セル / ボタン。 */
  readOnly?: boolean;
  /** test selector base。 */
  testid?: string;
}

/**
 * 2-D 数値テーブルを編集する primitive (SPEC-0017 §UI 設計)。
 *
 * - セル個別編集 + 行/列追加削除 + JSON モードフォールバック
 * - shape link: breakpoints の長さと一致しない場合に警告表示
 * - 50×50 を超えるとパフォーマンス警告
 *
 * @example
 *   <GridEditor
 *     value={[[0, 10], [20, 30]]}
 *     rowCountLink={bp_row.length}
 *     colCountLink={bp_col.length}
 *     onChange={(next) => updateBlock("table", next)}
 *   />
 */
export function GridEditor({
  value,
  onChange,
  rowLabels,
  colLabels,
  rowCountLink,
  colCountLink,
  readOnly = false,
  testid,
}: GridEditorProps): JSX.Element {
  const { t } = useTranslation();
  const [jsonMode, setJsonMode] = useState(false);

  const nRows = value.length;
  const nCols = nRows > 0 ? value[0]!.length : 0;

  const shapeMismatch =
    (rowCountLink !== undefined && rowCountLink !== nRows) ||
    (colCountLink !== undefined && colCountLink !== nCols);
  const tooLarge = nRows > GRID_WARNING_THRESHOLD || nCols > GRID_WARNING_THRESHOLD;

  const handleCellChange = (i: number, j: number, raw: string): void => {
    const trimmed = raw.trim();
    if (trimmed === "") return;
    // SPEC-0017 §エッジケース: "nan" / "inf" / "-inf" の明示文字列を許容
    // (table 内 nan は「未定義領域」表現として LookupTable2D が伝播する)。
    const lower = trimmed.toLowerCase();
    let parsed: number;
    if (lower === "nan") parsed = NaN;
    else if (lower === "inf" || lower === "+inf" || lower === "infinity") parsed = Infinity;
    else if (lower === "-inf" || lower === "-infinity") parsed = -Infinity;
    else {
      parsed = parseFloat(trimmed);
      if (Number.isNaN(parsed)) return;
    }
    const next = value.map((row, ri) =>
      ri === i ? row.map((v, ci) => (ci === j ? parsed : v)) : row.slice(),
    );
    onChange(next);
  };

  const handleAddRow = (): void => {
    const newRow = nCols > 0 ? new Array(nCols).fill(0) : [0];
    onChange([...value.map((r) => r.slice()), newRow]);
  };

  const handleAddCol = (): void => {
    if (nRows === 0) {
      onChange([[0]]);
      return;
    }
    onChange(value.map((row) => [...row, 0]));
  };

  const handleRemoveRow = (i: number): void => {
    if (nRows <= 1) return;
    onChange(value.filter((_, ri) => ri !== i).map((r) => r.slice()));
  };

  const handleRemoveCol = (j: number): void => {
    if (nCols <= 1) return;
    onChange(value.map((row) => row.filter((_, ci) => ci !== j)));
  };

  const handleJsonCommit = (parsed: unknown[]): void => {
    // 2-D 配列であることと、行ごとの長さが揃っていることを確認。
    // nan / inf は許容 (LookupTable2D が「未定義領域」として伝播するため、
    // table 内 NaN / Inf は UI でも保持する。SPEC-0017 §エッジケース)。
    if (!Array.isArray(parsed) || parsed.length === 0) return;
    const isRegular2D = parsed.every(
      (row) =>
        Array.isArray(row) &&
        row.length === (parsed[0] as unknown[]).length &&
        row.every((cell) => typeof cell === "number"),
    );
    if (!isRegular2D) return;
    onChange(parsed as number[][]);
    setJsonMode(false);
  };

  if (jsonMode) {
    return (
      <div className="flex flex-col gap-1" data-testid={testid}>
        <div className="flex items-center justify-end gap-1">
          <SecondaryButton
            onClick={() => setJsonMode(false)}
            testId={testid ? `${testid}-back-to-grid` : undefined}
          >
            {t("inspector.grid.back_to_grid")}
          </SecondaryButton>
        </div>
        <JsonArrayEditor
          value={value as unknown[]}
          elementType="number"
          onCommit={handleJsonCommit}
          testid={testid ? `${testid}-json` : undefined}
          widthClass="w-full"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1" data-testid={testid}>
      <div className="flex items-center justify-between gap-1">
        {tooLarge ? (
          <span className="text-[10px] text-amber-700" role="status">
            {t("inspector.grid.large_warning", { rows: nRows, cols: nCols })}
          </span>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-1">
          <SecondaryButton
            onClick={handleAddRow}
            disabled={readOnly}
            testId={testid ? `${testid}-add-row` : undefined}
          >
            {t("inspector.grid.add_row")}
          </SecondaryButton>
          <SecondaryButton
            onClick={handleAddCol}
            disabled={readOnly}
            testId={testid ? `${testid}-add-col` : undefined}
          >
            {t("inspector.grid.add_col")}
          </SecondaryButton>
          <SecondaryButton
            onClick={() => setJsonMode(true)}
            testId={testid ? `${testid}-to-json` : undefined}
          >
            {t("inspector.grid.json_mode")}
          </SecondaryButton>
        </div>
      </div>

      <table
        className="border-collapse border border-slate-400 text-[11px]"
        data-testid={testid ? `${testid}-table` : undefined}
      >
        <thead>
          <tr>
            <th className="w-8 border border-slate-400 bg-slate-100" />
            {Array.from({ length: nCols }, (_, j) => (
              <th
                key={`col-${j}`}
                className="group relative border border-slate-400 bg-slate-100 px-1 text-center font-normal text-slate-600"
              >
                <span>{colLabels?.[j] ?? `c[${j}]`}</span>
                {!readOnly && nCols > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveCol(j)}
                    className="absolute right-0 top-0 hidden h-4 w-4 cursor-pointer items-center justify-center text-rose-600 group-hover:flex"
                    aria-label={t("inspector.grid.remove_col", { index: j })}
                    data-testid={testid ? `${testid}-remove-col-${j}` : undefined}
                  >
                    ×
                  </button>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {value.map((row, i) => (
            <tr key={`row-${i}`} className="group">
              <th className="relative border border-slate-400 bg-slate-100 px-1 text-center font-normal text-slate-600">
                <span>{rowLabels?.[i] ?? `r[${i}]`}</span>
                {!readOnly && nRows > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveRow(i)}
                    className="absolute right-0 top-0 hidden h-4 w-4 cursor-pointer items-center justify-center text-rose-600 group-hover:flex"
                    aria-label={t("inspector.grid.remove_row", { index: i })}
                    data-testid={testid ? `${testid}-remove-row-${i}` : undefined}
                  >
                    ×
                  </button>
                )}
              </th>
              {row.map((cell, j) => (
                <td
                  key={`cell-${i}-${j}`}
                  className="border border-slate-400 p-0"
                >
                  <input
                    type="number"
                    step="any"
                    defaultValue={cell}
                    disabled={readOnly}
                    onBlur={(e) => handleCellChange(i, j, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.currentTarget.blur();
                      }
                    }}
                    className={`${INPUT_MONO_CLS} w-16 border-0`}
                    data-testid={
                      testid ? `${testid}-cell-${i}-${j}` : undefined
                    }
                    aria-label={
                      testid ? `${testid}-cell-${i}-${j}` : `cell-${i}-${j}`
                    }
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="text-[10px] text-slate-500" data-testid={testid ? `${testid}-shape` : undefined}>
        {shapeMismatch ? (
          <span className="text-amber-700" role="alert">
            {t("inspector.grid.shape_mismatch", {
              rows: nRows,
              cols: nCols,
              expectedRows: rowCountLink ?? nRows,
              expectedCols: colCountLink ?? nCols,
            })}
          </span>
        ) : (
          <span>
            {t("inspector.grid.shape", { rows: nRows, cols: nCols })}
          </span>
        )}
      </div>
    </div>
  );
}
