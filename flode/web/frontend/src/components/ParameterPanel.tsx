// ノードのパラメータ inline 編集パネル (右サイドバー = Inspector)。
// ADR-0012 §(3)、ADR-0019 §(5) auto-save 連動、ADR-0021 §(9) Mask Subsystem 編集。
//
// v0.25.0: ui/inspector.tsx primitives ベースに refactor、ScopeSettingsDialog /
// ModelSettingsModal と同じ Property Inspector スタイル (= PropertyGrid +
// SectionDivider + native widgets) に統一。
//
// editingModel + editingPath が source of truth。useAutoSave がそれを PUT する。

import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { isArrayCapableParam, parseArrayLiteral } from "../lib/arrayParams";
import { PYTHON_FUNCTION_TYPE } from "../lib/blockTypes";
import { findBlockAtPath, resolveBlocksAtPath } from "../lib/pathResolver";
import { useBlockRenameEditor } from "../lib/useBlockRename";
import {
  inferArrayElementType,
  isLongStringParam,
  isPrimitiveParam,
  parseNumericInput,
  withDependentParams,
} from "../lib/paramEdit";
import { indexRegistry } from "../lib/portShapeValidate";
import {
  toggleBlockFlipped,
  updateBlockParams,
  updateSubsystemMaskValues,
  useAppStore,
} from "../store/appStore";
import type { BlockEntry, MaskParamSpec } from "../types/api";
import { PythonFunctionEditor } from "./PythonFunctionEditor";
import { SignalDtypeSection } from "./SignalDtypeSection";
import {
  CHECKBOX_CLS,
  ExpressionEditor,
  INPUT_CLS,
  INPUT_MONO_CLS,
  GridEditor,
  JsonArrayEditor,
  PropertyGrid,
  PropertyHint,
  PropertyRow,
  SectionDivider,
  SELECT_CLS,
  TextInput,
} from "./ui/inspector";

interface ParameterPanelProps {
  modelId: string;
}

export function ParameterPanel({
  modelId: _modelId,
}: ParameterPanelProps): JSX.Element {
  const { t } = useTranslation();
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);

  const block = useMemo(() => {
    if (!editingModel || !selectedNodeId) return undefined;
    try {
      return findBlockAtPath(editingModel, editingPath, selectedNodeId);
    } catch {
      return undefined;
    }
  }, [editingModel, editingPath, selectedNodeId]);

  if (!selectedNodeId || !block) {
    return (
      <div
        data-testid="parameter-panel-empty"
        className="bg-white px-3 py-2 text-[11px] text-slate-500"
      >
        {t("inspector.empty")}
      </div>
    );
  }

  const maskParamsRaw = block.params.mask_params;
  const isMaskedSubsystem =
    Array.isArray(maskParamsRaw) && maskParamsRaw.length > 0;

  if (isMaskedSubsystem) {
    return (
      <MaskValuesEditor
        block={block}
        maskParams={maskParamsRaw as MaskParamSpec[]}
      />
    );
  }
  // SPEC-0023 / ADR-0073: PythonFunction はコードが SSOT の専用エディタ
  // (構造 read-only + コード + 動的パラメータ行)。
  if (block.type === PYTHON_FUNCTION_TYPE) {
    return (
      <PythonFunctionEditor
        block={block}
        header={<BlockHeader key={block.id} block={block} />}
      />
    );
  }
  return <RegularParamsEditor block={block} />;
}

// ---------------------------------------------------------------------------
// Block header (id + 型表示、Inspector 全モード共通)
// ---------------------------------------------------------------------------

function BlockHeader({
  block,
  subtitle,
}: {
  block: BlockEntry;
  subtitle?: string;
}): JSX.Element {
  const { t } = useTranslation();
  // SPEC-0022 §機能要件 1-1: id 表示をクリックで rename 編集に切り替える
  const editor = useBlockRenameEditor(block.id);
  const shortType = block.type.split(".").at(-1) ?? block.type;
  return (
    <div className="border-b border-slate-300 bg-gradient-to-b from-slate-100 to-slate-50 px-2 py-1">
      <div className="flex items-center justify-between gap-2">
        {editor.editing ? (
          <TextInput
            value={editor.draft}
            onChange={editor.setDraft}
            onBlur={editor.handleBlur}
            onKeyDown={editor.handleKeyDown}
            onCompositionStart={editor.handleCompositionStart}
            onCompositionEnd={editor.handleCompositionEnd}
            autoFocus
            widthClass="min-w-0 flex-1"
            testId="block-header-rename-input"
            ariaLabel={t("diagram.rename.aria_label")}
          />
        ) : (
          <button
            type="button"
            className="min-w-0 cursor-text truncate text-left text-[12px] font-semibold text-slate-800"
            title={`${block.id} — ${t("diagram.rename.hint")}`}
            data-testid="block-header-id"
            onClick={editor.start}
          >
            {block.id}
          </button>
        )}
        <span
          className="shrink-0 truncate font-mono text-[10px] text-slate-500"
          title={block.type}
        >
          {subtitle ? `${shortType} · ${subtitle}` : shortType}
        </span>
      </div>
      {editor.editing && editor.error !== null && (
        <div className="pb-0.5 text-[10px] text-rose-600" data-testid="block-header-rename-error">
          {t(`diagram.rename.${editor.error.code}`, {
            conflictId: editor.error.conflictId ?? "",
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 通常 block のパラメータ inline 編集
// ---------------------------------------------------------------------------

function RegularParamsEditor({ block }: { block: BlockEntry }): JSX.Element {
  const { t } = useTranslation();
  const { data: registryData } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  const registryMap = useMemo(
    () => indexRegistry(registryData?.blocks ?? []),
    [registryData],
  );

  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  const flippedNow = useMemo(() => {
    if (!editingModel) return false;
    try {
      const view = resolveBlocksAtPath(editingModel, editingPath);
      return Boolean(view.layout[block.id]?.flipped);
    } catch {
      return false;
    }
  }, [editingModel, editingPath, block.id]);

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const prevBlockIdRef = useRef<string | undefined>(undefined);

  const blockMeta = registryMap.get(block.type);

  // ブロック切替時に draft を最新値で初期化
  // SPEC-0016 v0.39.1 amendment: registry.params_spec で宣言されているが
  // block.params にない param も default 値で draft に入れて Inspector で
  // 編集可能にする (= 旧モデルでも新 param が表示される)。
  useEffect(() => {
    if (block.id === prevBlockIdRef.current) return;
    prevBlockIdRef.current = block.id;
    const next: Record<string, string> = {};
    const seen = new Set<string>();
    for (const [k, v] of Object.entries(block.params)) {
      if (isPrimitiveParam(v)) next[k] = formatForDraft(v);
      seen.add(k);
    }
    if (blockMeta) {
      for (const p of blockMeta.params_spec) {
        if (seen.has(p.name)) continue;
        if (p.has_default && isPrimitiveParam(p.default)) {
          next[p.name] = formatForDraft(p.default);
        }
      }
    }
    setDraft(next);
    setError(null);
  }, [block, blockMeta]);
  const allEntries = Object.entries(block.params);

  // SPEC-0016 v0.39.1 amendment: registry.params_spec に宣言されているが
  // block.params にない param を default 値で補完 (= 旧モデルで保存された
  // ブロックでも新 param を Inspector で編集可能にする)。
  // 旧モデル + 新 backend で FileWriter に path / format が追加されたケース
  // などに有効。commit 時に block.params に key が追加されて永続化される。
  const knownKeys = new Set(allEntries.map(([k]) => k));
  const missingEntries: [string, unknown][] = [];
  if (blockMeta) {
    for (const p of blockMeta.params_spec) {
      if (!knownKeys.has(p.name) && p.has_default) {
        missingEntries.push([p.name, p.default]);
      }
    }
  }
  const mergedEntries: [string, unknown][] = [...allEntries, ...missingEntries];

  const editableEntries = mergedEntries.filter(([, v]) => isPrimitiveParam(v));
  const readOnlyEntries = mergedEntries.filter(([, v]) => !isPrimitiveParam(v));
  const readOnlyJson = useMemo(
    () => JSON.stringify(Object.fromEntries(readOnlyEntries), null, 2),
    [readOnlyEntries],
  );

  // raw の型は originalType で分岐:
  //   - "number" / "boolean" / "string": raw は string (text input の値)
  //   - "array": raw は unknown[] (JsonArrayEditor が parse + 検証済の配列)
  const commit = (k: string, raw: unknown, originalType: string): void => {
    let newValue: unknown;
    if (originalType === "number" && isArrayCapableParam(block.type, k)) {
      // ADR-0079 Stage 3: スカラ ⇄ 配列を許すパラメータは ``[…]`` を配列として受ける
      const arr = parseArrayLiteral(raw as string);
      if (arr === null) {
        setError(t("inspector.array.element_type", { expected: "number" }));
        return;
      }
      if (arr !== undefined) {
        commit(k, arr, "array");
        return;
      }
    }
    if (originalType === "number") {
      // raw は string で来る (number 入力は text 入力経路)
      const parsed = parseNumericInput(raw as string);
      if (parsed === null) {
        setError(t("inspector.invalid_number", { name: k }));
        return;
      }
      const isIntParam =
        k === "n" ||
        k === "n_inputs" ||
        k === "n_outputs" ||
        k === "decimals" ||
        k === "port_idx";
      newValue = isIntParam ? Math.trunc(parsed) : parsed;
    } else if (originalType === "boolean") {
      newValue = raw === "true";
    } else if (originalType === "array") {
      // SPEC-0011: JsonArrayEditor が parse + 検証済の配列を直接渡す
      newValue = raw;
    } else {
      newValue = raw;
    }
    setError(null);
    const nextParams = withDependentParams(block, k, newValue);
    // 従属パラメータの追従 / clamp で実際に入る値が入力と異なるキーは draft も
    // 揃える (= 入力欄に「3」と残ったまま params は 1、という食い違いを防ぐ)
    setDraft((d) => {
      const out = { ...d };
      for (const [key, v] of Object.entries(nextParams)) {
        const changedByDependency = key !== k && block.params[key] !== v;
        const clamped = key === k && v !== newValue;
        if ((changedByDependency || clamped) && isPrimitiveParam(v)) {
          out[key] = formatForDraft(v);
        }
      }
      return out;
    });
    updateBlockParams(block.id, nextParams, registryMap);
  };

  return (
    <div
      data-testid="parameter-panel"
      className="flex h-full flex-col bg-white text-[11px]"
    >
      {/* key={block.id}: 選択切替・rename 確定時に rename editor 状態
          (editing/draft) を確実にリセットする (code-reviewer SHOULD-2) */}
      <BlockHeader key={block.id} block={block} />

      <div className="flex flex-1 flex-col overflow-y-auto px-3 py-2">
        <PropertyGrid>
          <SectionDivider
            label={t("inspector.section.layout", "Layout")}
          />
          <PropertyRow
            labelWidth={88} labelAlign="left"
            label={t("inspector.flip_horizontal", "Flip horizontal")}
          >
            <input
              type="checkbox"
              data-testid="flip-block-button"
              checked={flippedNow}
              onChange={() => toggleBlockFlipped(block.id)}
              title={t(
                "inspector.flip_horizontal_tooltip",
                "Flip block left/right",
              )}
              className={CHECKBOX_CLS}
            />
          </PropertyRow>

          <SectionDivider
            label={t("inspector.section.parameters", "Parameters")}
          />
          {editableEntries.length === 0 && (
            <div className="px-2 py-1 text-[11px] text-slate-500">
              {t("inspector.no_editable")}
            </div>
          )}
          {editableEntries.map(([k, v]) => {
            const valueType = typeof v;
            const enumValues = blockMeta?.params_spec.find(
              (p) => p.name === k,
            )?.enum_values;
            // SPEC-0028 Q6 (security MUST-1 対応): Subsystem 内部の dtype 宣言は
            // 未対応 (float64 island、backend が build 時に拒否) — 非 root スコープ
            // では select を無効化して「操作できるのに効かない/エラーになる」を防ぐ
            const dtypeDisabled = k === "dtype" && editingPath.length > 0;
            // SPEC-0030 (v0.58.0): sample_time は 3 モード select
            // (基準クロック "dt" / 継承 -1 / 指定)。ヒントは規則の説明の
            // み表示し、解決値のグラフ再計算は frontend でしない (二重実装回避)。
            // NOTE: 文言は「GUI で sample_time を露出するブロックは全て
            // requires_discrete_rate=True」という現状の前提に依存する。前提が
            // 崩れる新規ブロックを足す場合は registry 経由でフラグを渡して
            // 文言を分岐させること (SPEC-0030 §4)
            // 3 モード select は離散専用ブロック (registry の
            // requires_discrete_rate、backend ClassVar が SSOT) にのみ出す。
            // RandomSource 等 (>0 のみ受理) は従来の数値入力のまま —
            // 選ぶだけで不正値が commit される UI を作らない
            // (security SHOULD 2026-09-11)
            const sampleTimeMode =
              k !== "sample_time" || blockMeta?.requires_discrete_rate !== true
                ? null
                : v === "dt"
                  ? ("base" as const)
                  : valueType === "number"
                    ? v === -1
                      ? ("upstream" as const)
                      : ("explicit" as const)
                    : null;
            // Subsystem 内部では同期モードが build 拒否されるため option を
            // 無効化する (dtype select と同じ扱い)
            const syncedModesDisabled = editingPath.length > 0;
            const modelDt = (
              editingModel?.simulator as Record<string, unknown> | undefined
            )?.dt;
            const dtLabel = typeof modelDt === "number" ? modelDt : "?";
            const sampleTimeHint =
              sampleTimeMode === null
                ? null
                : sampleTimeMode === "base"
                  ? t("inspector.sample_time.base_hint", { dt: dtLabel })
                  : sampleTimeMode === "upstream"
                    ? t("inspector.sample_time.upstream_hint")
                    : t("inspector.sample_time.fixed_hint");
            return (
              <Fragment key={k}>
              <PropertyRow labelWidth={88} labelAlign="left" label={k}>
                {sampleTimeMode !== null ? (
                  <select
                    data-testid="param-sample-time-mode"
                    value={sampleTimeMode}
                    onChange={(e) => {
                      const mode = e.target.value;
                      if (mode === "base") {
                        setDraft((prev) => ({ ...prev, [k]: "dt" }));
                        commit(k, "dt", "string");
                      } else if (mode === "upstream") {
                        setDraft((prev) => ({ ...prev, [k]: "-1" }));
                        commit(k, "-1", "number");
                      } else {
                        // 指定へ切替: 現在の dt を初期値に転記 (値のコピー)
                        const seed = String(
                          typeof modelDt === "number" ? modelDt : 0.1,
                        );
                        setDraft((prev) => ({ ...prev, [k]: seed }));
                        commit(k, seed, "number");
                      }
                    }}
                    className={`${SELECT_CLS} min-w-0 flex-1 max-w-[140px]`}
                  >
                    <option value="base" disabled={syncedModesDisabled}>
                      {t("inspector.sample_time.mode.base", "基準クロック (dt)")}
                    </option>
                    <option value="upstream" disabled={syncedModesDisabled}>
                      {t("inspector.sample_time.mode.upstream", "継承")}
                    </option>
                    <option value="explicit">
                      {t("inspector.sample_time.mode.explicit", "指定")}
                    </option>
                  </select>
                ) : enumValues && enumValues.length > 0 ? (
                  <select
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? String(v)}
                    disabled={dtypeDisabled}
                    title={
                      dtypeDisabled
                        ? t(
                            "inspector.dtype.island",
                            "Subsystem / PythonFunction boundary is float64 in this release",
                          )
                        : undefined
                    }
                    onChange={(e) => {
                      setDraft((prev) => ({ ...prev, [k]: e.target.value }));
                      commit(k, e.target.value, "string");
                    }}
                    className={`${SELECT_CLS} min-w-0 flex-1 max-w-[140px]`}
                  >
                    {enumValues.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : valueType === "boolean" ? (
                  <select
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? "false"}
                    onChange={(e) => {
                      setDraft((prev) => ({ ...prev, [k]: e.target.value }));
                      commit(k, e.target.value, "boolean");
                    }}
                    className={`${SELECT_CLS} min-w-0 w-24`}
                  >
                    <option value="false">false</option>
                    <option value="true">true</option>
                  </select>
                ) : valueType === "number" ? (
                  <input
                    type="text"
                    inputMode="decimal"
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setDraft((prev) => ({ ...prev, [k]: val }));
                      if (val !== "" && parseNumericInput(val) !== null) {
                        commit(k, val, "number");
                      }
                    }}
                    onBlur={(e) => commit(k, e.target.value, "number")}
                    className={`${INPUT_MONO_CLS} min-w-0 flex-1 max-w-[140px]`}
                  />
                ) : Array.isArray(v) &&
                  Array.isArray(v[0]) &&
                  !Array.isArray((v[0] as unknown[])[0]) ? (
                  // SPEC-0017 §UI 設計: 2-D 配列を GridEditor で編集
                  // (3-D 以上は下の Array.isArray(v) 分岐で JsonArrayEditor へ、
                  //  SPEC-0018 MVP: slice viewer は Phase 2 で実装)
                  <GridEditor
                    value={v as number[][]}
                    rowCountLink={
                      Array.isArray(
                        (block.params as Record<string, unknown>)["breakpoints_row"],
                      )
                        ? (
                            (block.params as Record<string, unknown>)[
                              "breakpoints_row"
                            ] as unknown[]
                          ).length
                        : undefined
                    }
                    colCountLink={
                      Array.isArray(
                        (block.params as Record<string, unknown>)["breakpoints_col"],
                      )
                        ? (
                            (block.params as Record<string, unknown>)[
                              "breakpoints_col"
                            ] as unknown[]
                          ).length
                        : undefined
                    }
                    testid={`param-input-${k}`}
                    onChange={(next) => commit(k, next, "array")}
                  />
                ) : Array.isArray(v) ? (
                  // SPEC-0011 §1.1: 1-D 配列を JsonArrayEditor で編集
                  // SPEC-0018: 3-D 以上の n-D 数値配列 (= LookupTableND.table)
                  // も elementType="nested" でここに流れる (Phase 1 = JSON 編集のみ)
                  <JsonArrayEditor
                    value={v}
                    elementType={
                      Array.isArray(v[0])
                        ? "nested"
                        : inferArrayElementType(v)
                    }
                    testid={`param-input-${k}`}
                    placeholder={t(
                      "inspector.array.placeholder",
                      "e.g. [0.0, 1.0, 2.0]",
                    )}
                    onCommit={(next) => commit(k, next, "array")}
                    // ADR-0079 Stage 3: 配列 → スカラに戻す (数値 1 個を書く)
                    onCommitScalar={
                      isArrayCapableParam(block.type, k)
                        ? (n) => commit(k, String(n), "number")
                        : undefined
                    }
                  />
                ) : valueType === "string" &&
                  isLongStringParam(v as string) ? (
                  // SPEC-0011 §1.2: 長文字列 (40 chars 超 or 改行) を ExpressionEditor
                  <ExpressionEditor
                    value={v as string}
                    testid={`param-input-${k}`}
                    placeholder={t(
                      "inspector.expression.placeholder",
                      "e.g. u[0]**2 + sin(t)",
                    )}
                    onCommit={(next) => commit(k, next, "string")}
                  />
                ) : (
                  <input
                    type="text"
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setDraft((prev) => ({ ...prev, [k]: val }));
                      commit(k, val, "string");
                    }}
                    onBlur={(e) => commit(k, e.target.value, "string")}
                    className={`${INPUT_CLS} min-w-0 flex-1 max-w-[140px]`}
                  />
                )}
              </PropertyRow>
              {sampleTimeMode === "explicit" && (
                // 「指定」時の周期入力は横並びではなく下のインデント行に出す
                // (dt_base 明示指定 → 値 の既存パターン、オーナー指摘 2026-09-12)
                <PropertyRow
                  indent
                  labelWidth={88}
                  labelAlign="left"
                  label={t("inspector.sample_time.period_label", "周期 (秒)")}
                >
                  <input
                    type="text"
                    inputMode="decimal"
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? String(v)}
                    onChange={(e) => {
                      const val = e.target.value;
                      setDraft((prev) => ({ ...prev, [k]: val }));
                      if (val !== "" && parseNumericInput(val) !== null) {
                        commit(k, val, "number");
                      }
                    }}
                    onBlur={(e) => commit(k, e.target.value, "number")}
                    className={`${INPUT_MONO_CLS} min-w-0 flex-1 max-w-[140px]`}
                  />
                </PropertyRow>
              )}
              {sampleTimeHint !== null && (
                <PropertyHint
                  testId="param-hint-sample-time"
                  labelWidth={88}
                  text={sampleTimeHint}
                />
              )}
              </Fragment>
            );
          })}

          {readOnlyEntries.length > 0 && (
            <>
              <SectionDivider
                label={t("inspector.section.read_only", "Read only")}
              />
              <details className="border border-slate-300 bg-slate-50 px-2 py-1">
                <summary className="cursor-pointer text-[11px] text-slate-600">
                  {t("inspector.read_only_summary", {
                    count: readOnlyEntries.length,
                  })}
                </summary>
                <pre className="mt-1 overflow-auto font-mono text-[10px] text-slate-700">
                  {readOnlyJson}
                </pre>
              </details>
            </>
          )}

          {/* SPEC-0027 (SM-D Stage 0): 影の型表示 (read-only、失敗時は非表示) */}
          <SignalDtypeSection blockId={block.id} />

          {error && (
            <div
              role="alert"
              className="mt-2 border border-rose-300 bg-rose-50 px-2 py-1 text-[11px] text-rose-700"
            >
              {error}
            </div>
          )}
        </PropertyGrid>
      </div>

      <div className="border-t border-slate-200 bg-slate-50 px-3 py-1 text-[10px] text-slate-500">
        {t("inspector.autosave_hint")}
      </div>
    </div>
  );
}

function formatForDraft(v: number | string | boolean | unknown[]): string {
  if (typeof v === "boolean") return v ? "true" : "false";
  // SPEC-0011: array は JSON 形式で draft に保持 (JsonArrayEditor の初期表示と
  // 整合)。実際の render path では Array.isArray 分岐で JsonArrayEditor が
  // 自身の draft state を持つため、ここの draft は使われない (= 安全な fallback)
  if (Array.isArray(v)) return JSON.stringify(v);
  return String(v);
}

// ---------------------------------------------------------------------------
// Mask Subsystem 編集 (ADR-0021 §(9))
// ---------------------------------------------------------------------------

function MaskValuesEditor({
  block,
  maskParams,
}: {
  block: BlockEntry;
  maskParams: MaskParamSpec[];
}): JSX.Element {
  const { t } = useTranslation();
  const initialValues = useMemo(() => {
    const fromBlock = block.params.mask_values as
      | Record<string, unknown>
      | undefined;
    const out: Record<string, string> = {};
    for (const p of maskParams) {
      const v = fromBlock?.[p.name] ?? p.default;
      out[p.name] = v === null || v === undefined ? "" : String(v);
    }
    return out;
  }, [block.id, block.params.mask_values, maskParams]);

  const [draft, setDraft] = useState<Record<string, string>>(initialValues);
  const [error, setError] = useState<string | null>(null);
  const prevBlockIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (block.id === prevBlockIdRef.current) return;
    prevBlockIdRef.current = block.id;
    setDraft(initialValues);
    setError(null);
  }, [block.id, initialValues]);

  const commit = (
    name: string,
    raw: string,
    type: MaskParamSpec["type"],
  ): void => {
    let parsed: number | boolean;
    if (type === "bool") {
      parsed = raw === "true" || raw === "1";
    } else {
      const n = parseNumericInput(raw);
      if (n === null) {
        setError(t("inspector.invalid_number", { name }));
        return;
      }
      parsed = type === "int" ? Math.trunc(n) : n;
    }
    setError(null);
    const next: Record<string, number | boolean> = {};
    for (const p of maskParams) {
      if (p.name === name) {
        next[p.name] = parsed;
      } else {
        const existing = draft[p.name] ?? "";
        if (p.type === "bool") {
          next[p.name] = existing === "true" || existing === "1";
        } else {
          const existingNum = parseNumericInput(existing);
          next[p.name] =
            existingNum === null
              ? typeof p.default === "number"
                ? p.default
                : 0
              : p.type === "int"
                ? Math.trunc(existingNum)
                : existingNum;
        }
      }
    }
    updateSubsystemMaskValues(block.id, next);
  };

  return (
    <div
      data-testid="parameter-panel-mask"
      className="flex h-full flex-col bg-white text-[11px]"
    >
      <BlockHeader key={block.id} block={block} subtitle={t("inspector.mask.suffix")} />

      <div className="flex flex-1 flex-col overflow-y-auto px-3 py-2">
        <PropertyGrid>
          <SectionDivider
            label={t("inspector.section.mask_params", "Mask parameters")}
          />
          {maskParams.map((p) => (
            <PropertyRow
              key={p.name}
              labelWidth={88} labelAlign="left"
              label={`${p.name} (${p.type})`}
            >
              {p.type === "bool" ? (
                <select
                  data-testid={`mask-input-${p.name}`}
                  value={draft[p.name] ?? "false"}
                  onChange={(e) => {
                    setDraft((prev) => ({ ...prev, [p.name]: e.target.value }));
                    commit(p.name, e.target.value, p.type);
                  }}
                  className={`${SELECT_CLS} min-w-0 w-24`}
                >
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              ) : (
                <input
                  type="text"
                  inputMode={p.type === "int" ? "numeric" : "decimal"}
                  data-testid={`mask-input-${p.name}`}
                  value={draft[p.name] ?? ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    setDraft((prev) => ({ ...prev, [p.name]: val }));
                    if (val !== "" && parseNumericInput(val) !== null) {
                      commit(p.name, val, p.type);
                    }
                  }}
                  onBlur={(e) => commit(p.name, e.target.value, p.type)}
                  className={`${INPUT_MONO_CLS} min-w-0 flex-1 max-w-[140px]`}
                />
              )}
            </PropertyRow>
          ))}

          {/* descriptions が長いと PropertyRow に収まらないので、別レイアウトで
              下に並べる */}
          {maskParams.some((p) => p.description) && (
            <div className="mt-2 flex flex-col gap-1">
              {maskParams.map(
                (p) =>
                  p.description && (
                    <div
                      key={p.name}
                      className="text-[10px] text-slate-500"
                    >
                      <span className="font-mono text-slate-600">{p.name}</span>
                      : {p.description}
                    </div>
                  ),
              )}
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="mt-2 border border-rose-300 bg-rose-50 px-2 py-1 text-[11px] text-rose-700"
            >
              {error}
            </div>
          )}
        </PropertyGrid>
      </div>

      <div className="border-t border-slate-200 bg-slate-50 px-3 py-1 text-[10px] text-slate-500">
        {t("inspector.mask.autosave_hint")}
      </div>
    </div>
  );
}
