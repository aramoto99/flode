// SPEC-0028 (SM-D Stage 1) / ADR-0079 (SM-T Stage 1): Inspector の「信号」セクション。
//
// Stage 0 の「(shadow)」表記と shadow_note (「結果に影響しません」) は撤去された
// (AC-9) — Stage 1 では宣言 dtype が**実際に計算に効く**ため。
// dtype 未宣言モデルでは代わりに auto_note (すべて float64 で計算) を出す。
// ADR-0079 §(9): 各ポート行に解決済み shape を併記する (既存 primitives のみ、
// 新 idiom ゼロ)。`shape.*` 診断はポート行の下にヒントとして出す。
//
// 設計制約:
// - 表示のみ。frontend で dtype / shape を再計算しない (ADR-0077 §データ整合性 1 SSOT)
// - データ取得はモデルレベル store (lib/dtypeResolution.ts、DiagramCanvas が
//   300ms debounce で fetch) — Display の表示整形と同じ結果を共有する
// - "unknown" 表示は static mode (PythonFunction 入り REST 解決) 用に温存
// - Stage 0 は root スコープのみ対象 → Subsystem 内を編集中は表示しない

import { useTranslation } from "react-i18next";

import { formatShape, hasDeclaredDtype, useDtypeResolution } from "../lib/dtypeResolution";
import { useAppStore } from "../store/appStore";
import type { DtypesDiagnostic, DtypesPortEntry, DtypesResponse } from "../types/api";
import { PropertyHint, PropertyRow, SectionDivider } from "./ui/inspector";

/** Inspector 狭幅レイアウトのラベル幅 (ParameterPanel の既存行と揃える)。 */
const LABEL_W = 88;

/**
 * editingPath (Subsystem id の列) に対応するスコープの解決結果を返す。
 * 途中で ``inner`` が無ければ null (= セクション非表示)。
 */
export function resolveScope(
  root: DtypesResponse | null,
  path: readonly string[],
): DtypesResponse | null {
  let cur: DtypesResponse | null = root;
  for (const id of path) {
    if (!cur || !cur.inner) return null;
    cur = cur.inner[id] ?? null;
  }
  return cur;
}

interface SignalDtypeSectionProps {
  /** 選択中ブロックの id。 */
  blockId: string;
}

/**
 * 選択中ブロックの解決済み dtype を表示する read-only セクション。
 *
 * 取得失敗・未取得・root 以外のスコープ編集中は何も描画しない。
 */
export function SignalDtypeSection({ blockId }: SignalDtypeSectionProps): JSX.Element | null {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  const rootData = useDtypeResolution();

  // ADR-0079 §(6) (Stage 2): Subsystem 内を編集中は ``inner`` を editingPath で辿る
  // (Stage 1 以前の応答には inner が無いので root 以外は非表示のまま)。
  const data = resolveScope(rootData, editingPath);
  if (!data) return null;

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

  const declared = hasDeclaredDtype(editingModel);

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

  const islandHint = data.diagnostics.some(
    (d) => d.code === "dtype.opaque_float64_island" && d.block_id === blockId,
  );
  const stateHint = data.diagnostics.some(
    (d) => d.code === "dtype.state_via_float64" && d.block_id === blockId,
  );

  // ADR-0079 §(8): このブロックのポートに紐づく shape.* 診断 (error は赤字で出す)
  const shapeDiagnosticsFor = (p: DtypesPortEntry): DtypesDiagnostic[] =>
    data.diagnostics.filter(
      (d) =>
        d.code.startsWith("shape.") &&
        d.block_id === blockId &&
        d.direction === p.direction &&
        d.port_index === p.port_index &&
        d.code !== "shape.defaulted_to_scalar",
    );
  // shape 表示は "signals.v1" 以降 (= いずれかの port に shape がある) のみ
  const hasShape = rows.some((p) => p.shape !== undefined);

  return (
    <>
      <SectionDivider
        label={
          hasShape
            ? t("inspector.section.signal", "Signal")
            : t("inspector.section.signal_dtype", "Signal dtype")
        }
      />
      {rows.map((p) => {
        const hint = widenedHint(p);
        const shapeDiags = shapeDiagnosticsFor(p);
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
              {hasShape && (
                <span
                  data-testid={`shape-${p.direction}-${p.port_index}`}
                  className="ml-2 font-mono text-[11px] tabular-nums text-slate-500"
                  title={t("inspector.shape.title", "Resolved signal shape")}
                >
                  {p.shape === undefined || p.shape === null ? "—" : formatShape(p.shape)}
                </span>
              )}
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
            {shapeDiags.map((d) => (
              <PropertyHint
                key={d.code}
                labelWidth={LABEL_W}
                text={
                  d.severity === "error"
                    ? t("inspector.shape.error", {
                        message: d.message,
                        defaultValue: `Shape error: ${d.message}`,
                      })
                    : d.message
                }
                testId={`shape-diag-${p.direction}-${p.port_index}`}
              />
            ))}
          </div>
        );
      })}
      {islandHint && (
        <PropertyHint
          labelWidth={0}
          text={t(
            "inspector.dtype.island",
            "Subsystem / PythonFunction boundary is float64 in this release",
          )}
          testId="dtype-island-note"
        />
      )}
      {stateHint && (
        <PropertyHint
          labelWidth={0}
          text={t(
            "inspector.dtype.state_via_float64",
            "State is stored as float64 in this release",
          )}
          testId="dtype-state-note"
        />
      )}
      {!declared && (
        <PropertyHint
          labelWidth={0}
          text={t(
            "inspector.dtype.auto_note",
            "No dtype declared — all signals run as float64.",
          )}
          testId="dtype-auto-note"
        />
      )}
    </>
  );
}
