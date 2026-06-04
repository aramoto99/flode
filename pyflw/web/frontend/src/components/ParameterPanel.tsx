// ノードのパラメータ inline 編集パネル (右サイドバー = Inspector)。
// ADR-0012 §(3)、ADR-0019 §(5) auto-save 連動、ADR-0021 §(9) Mask Subsystem 編集。
//
// v0.25.0: ui/inspector.tsx primitives ベースに refactor、ScopeSettingsDialog /
// ModelSettingsModal と同じ Property Inspector スタイル (= PropertyGrid +
// SectionDivider + native widgets) に統一。
//
// editingModel + editingPath が source of truth。useAutoSave がそれを PUT する。

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { findBlockAtPath, resolveBlocksAtPath } from "../lib/pathResolver";
import {
  inferArrayElementType,
  isLongStringParam,
  isPrimitiveParam,
  parseNumericInput,
} from "../lib/paramEdit";
import { indexRegistry } from "../lib/portShapeValidate";
import {
  toggleBlockFlipped,
  updateBlockParams,
  updateSubsystemMaskValues,
  useAppStore,
} from "../store/appStore";
import type { BlockEntry, MaskParamSpec } from "../types/api";
import {
  CHECKBOX_CLS,
  ExpressionEditor,
  INPUT_CLS,
  INPUT_MONO_CLS,
  GridEditor,
  JsonArrayEditor,
  PropertyGrid,
  PropertyRow,
  SectionDivider,
  SELECT_CLS,
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
  const shortType = block.type.split(".").at(-1) ?? block.type;
  return (
    <div className="flex items-center justify-between gap-2 border-b border-slate-300 bg-gradient-to-b from-slate-100 to-slate-50 px-2 py-1">
      <span
        className="truncate text-[12px] font-semibold text-slate-800"
        title={block.id}
      >
        {block.id}
      </span>
      <span
        className="truncate font-mono text-[10px] text-slate-500"
        title={block.type}
      >
        {subtitle ? `${shortType} · ${subtitle}` : shortType}
      </span>
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

  // ブロック切替時に draft を最新値で初期化
  useEffect(() => {
    if (block.id === prevBlockIdRef.current) return;
    prevBlockIdRef.current = block.id;
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(block.params)) {
      if (isPrimitiveParam(v)) next[k] = formatForDraft(v);
    }
    setDraft(next);
    setError(null);
  }, [block]);

  const allEntries = Object.entries(block.params);
  const editableEntries = allEntries.filter(([, v]) => isPrimitiveParam(v));
  const readOnlyEntries = allEntries.filter(([, v]) => !isPrimitiveParam(v));
  const readOnlyJson = useMemo(
    () => JSON.stringify(Object.fromEntries(readOnlyEntries), null, 2),
    [readOnlyEntries],
  );
  const blockMeta = registryMap.get(block.type);

  // raw の型は originalType で分岐:
  //   - "number" / "boolean" / "string": raw は string (text input の値)
  //   - "array": raw は unknown[] (JsonArrayEditor が parse + 検証済の配列)
  const commit = (k: string, raw: unknown, originalType: string): void => {
    let newValue: unknown;
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
    updateBlockParams(
      block.id,
      { ...block.params, [k]: newValue },
      registryMap,
    );
  };

  return (
    <div
      data-testid="parameter-panel"
      className="flex h-full flex-col bg-white text-[11px]"
    >
      <BlockHeader block={block} />

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
            return (
              <PropertyRow key={k} labelWidth={88} labelAlign="left" label={k}>
                {enumValues && enumValues.length > 0 ? (
                  <select
                    data-testid={`param-input-${k}`}
                    value={draft[k] ?? String(v)}
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
                ) : Array.isArray(v) && Array.isArray(v[0]) ? (
                  // SPEC-0017 §UI 設計: 2-D 配列を GridEditor で編集
                  // breakpoints_row / breakpoints_col の長さで shape link 警告
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
                  <JsonArrayEditor
                    value={v}
                    elementType={inferArrayElementType(v)}
                    testid={`param-input-${k}`}
                    placeholder={t(
                      "inspector.array.placeholder",
                      "e.g. [0.0, 1.0, 2.0]",
                    )}
                    onCommit={(next) => commit(k, next, "array")}
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
      <BlockHeader block={block} subtitle={t("inspector.mask.suffix")} />

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
