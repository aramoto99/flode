// ADR-0056 §F5 / §F7-F8: Scope tab strip の Error tab がアクティブな時に
// 描画される失敗詳細パネル。
//
// 構成 (上から):
//   * 1 行目: プレフィックス (起動失敗: / 実行中エラー:) + テンプレートレンダリング
//   * 2 行目: 関与ブロックチップ + 「Diagram で表示」ボタン
//   * 3 行目: シミュレーション時刻 (起動失敗時は非表示)
//   * 折り畳み: 詳細 (traceback) + コピー
//
// すべて `inspector.tsx` primitives + Tailwind の slate / rose に統一。

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAppStore } from "../store/appStore";
import type { FailurePayload } from "../types/api";

/** Phase 1 で frontend が認識する template_key 一覧。未知 key は ``error.unknown``
 *  に fallback する (ADR-0056 §D-3)。 */
const _KNOWN_TEMPLATE_KEYS = new Set([
  "error.algebraic_loop",
  "error.shape_mismatch",
  "error.divide_by_zero",
  "error.solver_failure",
  "error.start_validation",
  "error.unknown",
  // SPEC-0023 / ADR-0073 §論点 6
  "error.python_function_error",
  "error.python_function_disabled",
  "error.python_function_unconfirmed",
]);

function _resolvedTemplateKey(payload: FailurePayload): string {
  return _KNOWN_TEMPLATE_KEYS.has(payload.template_key)
    ? payload.template_key
    : "error.unknown";
}

/** メッセージ本文中の ``blockLabel`` 部分をクリック可能リンクに置換する。
 *
 * substring split で先頭一致箇所のみリンク化する (= block label は識別子なので
 * 通常一意)。``blockLabel`` / ``blockId`` が無い、または本文に出現しない場合は
 * プレーン text のまま返す (= solver_failure / start_validation など)。
 */
function renderBodyWithBlockLink(
  body: string,
  blockLabel: string | null,
  blockId: string | null,
  onJump: (id: string) => void,
): React.ReactNode {
  if (!blockLabel || !blockId) return body;
  const idx = body.indexOf(blockLabel);
  if (idx < 0) return body;
  return (
    <>
      {body.slice(0, idx)}
      <button
        type="button"
        onClick={() => onJump(blockId)}
        className="text-sky-700 underline decoration-dotted underline-offset-2 hover:text-sky-900"
      >
        {blockLabel}
      </button>
      {body.slice(idx + blockLabel.length)}
    </>
  );
}

export function ErrorView(): JSX.Element {
  const { t } = useTranslation();
  const lastFailure = useAppStore((s) => s.lastFailure);
  const lastFailureSource = useAppStore((s) => s.lastFailureSource);
  const focusBlock = useAppStore((s) => s.focusBlock);
  const [detailsOpen, setDetailsOpen] = useState(false);

  if (lastFailure === null) {
    return (
      <div className="flex h-full items-center justify-center bg-white p-3 text-center text-[11px] text-slate-400">
        {t("log.empty", "ログはまだありません")}
      </div>
    );
  }

  const prefixKey =
    lastFailureSource === "start"
      ? "error.prefix.start_failed"
      : "error.prefix.runtime_failed";
  const templateKey = _resolvedTemplateKey(lastFailure);
  // i18next interpolation。``template_args`` を直接渡すと t_sec / block_labels
  // formatter (= i18n/index.ts の interpolation.format) でフォーマットされる。
  // ``templateKey`` は runtime 解決の string なので known key union への cast を経由
  // させて t() の 2 引数 overload (= key + opts) を選ばせる。
  const opts = {
    ...lastFailure.template_args,
    // unknown fallback では raw_message が必須。
    raw_message:
      typeof lastFailure.template_args.raw_message === "string"
        ? lastFailure.template_args.raw_message
        : lastFailure.raw_message,
  };
  const body: string = t(templateKey as "error.unknown", opts);
  const prefix = t(prefixKey as "error.prefix.runtime_failed");

  const copyDetails = () => {
    const text = lastFailure.raw_traceback ?? lastFailure.raw_message;
    void navigator.clipboard?.writeText(text);
  };

  const hasBlockTarget =
    lastFailure.block_ids.length > 0 || lastFailure.block_id !== null;
  // 単一ブロックが本文中でインラインリンク化されているか (= 本文クリックでジャンプ
  // できる状態)。renderBodyWithBlockLink と同じ条件で判定する。
  const inlineLinked =
    lastFailure.block_ids.length <= 1 &&
    !!lastFailure.block_label &&
    lastFailure.block_id !== null &&
    body.includes(lastFailure.block_label);
  // チップは「本文にインラインリンクが無い」ときだけ出す (= 重複を避けつつ、
  // ジャンプ手段を常に 1 つ確保する)。複数ブロックは全 ID、単一は 1 個。
  const showChips = hasBlockTarget && !inlineLinked;
  const chipIds =
    lastFailure.block_ids.length > 0
      ? lastFailure.block_ids
      : lastFailure.block_id !== null
        ? [lastFailure.block_id]
        : [];

  return (
    <div
      role="alert"
      aria-live="polite"
      className="flex h-full w-full flex-col overflow-auto bg-white p-3 text-[11px] text-slate-800"
    >
      {/* 1 行目: プレフィックス + 本文 (= ブロック名はインラインリンク) */}
      <div className="font-medium text-rose-700">
        {prefix}
        <span className="text-slate-800">
          {renderBodyWithBlockLink(
            body,
            // 複数ブロック時は本文をインラインリンク化せず、下のチップに委ねる
            // (= 本文に block_labels が "a, b, c" と並ぶため一意に張れない)。
            lastFailure.block_ids.length > 1 ? null : lastFailure.block_label,
            lastFailure.block_id,
            focusBlock,
          )}
        </span>
      </div>

      {/* 2 行目: 関与ブロックチップ (= 各クリックで対象へジャンプ)。
          本文がインラインリンク済の単一ブロックでは出さない (= 重複回避)。
          複数ブロック (代数ループ等) / 本文にブロック名が出ない失敗で使う。 */}
      {showChips && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {chipIds.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => focusBlock(id)}
              className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-700 hover:bg-slate-100"
            >
              {id}
            </button>
          ))}
        </div>
      )}

      {/* 3 行目: シミュレーション時刻 */}
      {lastFailure.t !== null && (
        <div className="mt-1 font-mono text-[10px] text-slate-500">
          t = {lastFailure.t.toFixed(3)}s
        </div>
      )}

      {/* 折り畳み: 詳細 (traceback) */}
      {lastFailure.raw_traceback && (
        <details
          className="mt-2"
          open={detailsOpen}
          onToggle={(e) => setDetailsOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary className="cursor-pointer select-none text-[11px] text-slate-600 hover:text-slate-800">
            {t("error.show_details", "詳細 (traceback)")}
          </summary>
          <div className="mt-1 flex items-start gap-2">
            <pre className="flex-1 overflow-auto whitespace-pre-wrap rounded border border-slate-300 bg-slate-50 p-2 font-mono text-[10px] text-slate-700">
              {lastFailure.raw_traceback}
            </pre>
            <button
              type="button"
              onClick={copyDetails}
              className="shrink-0 rounded border border-slate-400 bg-white px-2 py-0.5 text-[10px] text-slate-700 hover:bg-slate-100"
            >
              {t("error.copy", "コピー")}
            </button>
          </div>
        </details>
      )}
    </div>
  );
}
