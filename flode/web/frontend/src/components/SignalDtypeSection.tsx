// SPEC-0027 (SM-D Stage 0): Inspector の read-only「信号型 (shadow)」セクション。
//
// 選択中ブロックの各ポートについて、backend の影の型解決
// (POST /api/v1/models/resolve-dtypes) の結果を表示する。
//
// 設計制約 (SPEC-0027 §5.3):
// - 表示のみ。frontend で dtype を再計算しない (ADR-0077 §データ整合性 1 SSOT)
// - 編集後 + 選択変更後 300ms debounce で取得、旧リクエストは AbortController
//   で破棄 (Q3)
// - 未取得 / 取得失敗 → セクションごと非表示 (Toast なし、編集を妨げない)
// - "unknown" は "—" + 補足 hint (Q4)
// - 末尾の shadow_note は必須 (「型が見えるのに結果が変わらない」誤解の防止)
// - Stage 0 は root スコープのみ対象 → Subsystem 内を編集中は表示しない
// - 別ファイル化により ParameterPanel.tsx への diff を最小化 (AC-6 の可逆性)

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { resolveModelDtypes } from "../api/client";
import { useAppStore } from "../store/appStore";
import type { DtypesPortEntry, DtypesResponse } from "../types/api";
import { PropertyHint, PropertyRow, SectionDivider } from "./ui/inspector";

/** 編集 / 選択変更から取得までの debounce (SPEC-0027 Q3)。 */
const RESOLVE_DEBOUNCE_MS = 300;

/** Inspector 狭幅レイアウトのラベル幅 (ParameterPanel の既存行と揃える)。 */
const LABEL_W = 88;

interface SignalDtypeSectionProps {
  /** 選択中ブロックの id。 */
  blockId: string;
}

/**
 * 選択中ブロックの推論 dtype を表示する read-only セクション。
 *
 * 取得失敗・未取得・root 以外のスコープ編集中は何も描画しない。
 */
export function SignalDtypeSection({ blockId }: SignalDtypeSectionProps): JSX.Element | null {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  const [data, setData] = useState<DtypesResponse | null>(null);

  const isRootScope = editingPath.length === 0;

  useEffect(() => {
    if (!editingModel || !isRootScope) {
      setData(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await resolveModelDtypes(editingModel, controller.signal);
          if (!controller.signal.aborted) setData(res);
        } catch {
          // 失敗 / Abort はセクション非表示に落とすだけ (SPEC-0027 §5.3)。
          if (!controller.signal.aborted) setData(null);
        }
      })();
    }, RESOLVE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [editingModel, isRootScope, blockId]);

  if (!data || !isRootScope) return null;

  const rows = data.ports
    .filter((p) => p.block_id === blockId)
    .sort((a, b) =>
      a.direction === b.direction
        ? a.port_index - b.port_index
        : a.direction === "in"
          ? -1
          : 1,
    );
  if (rows.length === 0) return null;

  const widenedHint = (p: DtypesPortEntry): string | null => {
    if (p.direction !== "in") return null;
    const d = data.diagnostics.find(
      (diag) =>
        diag.code === "dtype.implicit_widening" &&
        diag.block_id === blockId &&
        diag.direction === "in" &&
        diag.port_index === p.port_index,
    );
    if (!d || d.from_dtype === null || d.to_dtype === null) return null;
    return t("inspector.dtype.widened", {
      from: d.from_dtype,
      to: d.to_dtype,
      defaultValue: `Widened from ${d.from_dtype} to ${d.to_dtype}`,
    });
  };

  return (
    <>
      <SectionDivider
        label={t("inspector.section.signal_dtype", "Signal dtype (shadow)")}
      />
      {rows.map((p) => {
        const hint = widenedHint(p);
        return (
          <div key={`${p.direction}-${p.port_index}`}>
            <PropertyRow
              label={`${p.direction}[${p.port_index}]`}
              labelWidth={LABEL_W}
              labelAlign="left"
            >
              <span
                data-testid={`dtype-${p.direction}-${p.port_index}`}
                className="font-mono text-[11px] tabular-nums text-slate-700"
              >
                {p.dtype === "unknown" ? "—" : p.dtype}
              </span>
            </PropertyRow>
            {p.dtype === "unknown" && (
              <PropertyHint
                labelWidth={LABEL_W}
                text={t("inspector.dtype.unresolved", "Not resolved in this release")}
                testId={`dtype-unresolved-${p.direction}-${p.port_index}`}
              />
            )}
            {hint !== null && (
              <PropertyHint
                labelWidth={LABEL_W}
                text={hint}
                testId={`dtype-widened-${p.port_index}`}
              />
            )}
          </div>
        );
      })}
      <PropertyHint
        labelWidth={0}
        text={t(
          "inspector.dtype.shadow_note",
          "Display only — does not affect simulation results.",
        )}
        testId="dtype-shadow-note"
      />
    </>
  );
}
