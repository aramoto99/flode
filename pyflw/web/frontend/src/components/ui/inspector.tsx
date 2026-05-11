// pyflw UI design system — "Simulink Property Inspector" 風 primitives。
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

import { useEffect } from "react";

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
 */
export function PropertyRow({
  label,
  children,
  indent = false,
  labelWidth = 140,
}: {
  label: string;
  children: React.ReactNode;
  indent?: boolean;
  labelWidth?: number;
}): JSX.Element {
  return (
    <div className="flex min-h-[22px] items-center gap-2 py-0.5">
      <label
        className={`shrink-0 text-right text-[11px] text-slate-700 ${
          indent ? "pl-3" : ""
        }`}
        style={{ width: `${labelWidth}px` }}
      >
        {label}:
      </label>
      <div className="flex flex-1 items-center">{children}</div>
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
// Dialog shell (Simulink "Configuration Parameters" 風)
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
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="flex items-end gap-0 border-b border-slate-400 bg-slate-100 pl-2 pt-1">
      {children}
    </div>
  );
}

export function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px border border-b-0 px-3 py-0.5 text-[11px] ${
        active
          ? "border-slate-400 bg-white text-slate-800 font-medium"
          : "border-transparent bg-slate-100 text-slate-600 hover:text-slate-800"
      }`}
    >
      {children}
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
