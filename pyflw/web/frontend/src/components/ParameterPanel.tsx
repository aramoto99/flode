// ノードのパラメータ inline 編集パネル (ADR-0012 §(3)、ADR-0019 §(5) auto-save 連動、
// ADR-0021 §(9) で Subsystem の mask_values 編集モードを追加)。
//
// editingModel + editingPath が source of truth。useAutoSave がそれを PUT する。

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { findBlockAtPath } from "../lib/pathResolver";
import {
  isPrimitiveParam,
  parseNumericInput,
} from "../lib/paramEdit";
import { indexRegistry } from "../lib/portShapeValidate";
import {
  updateBlockParams,
  updateSubsystemMaskValues,
  useAppStore,
} from "../store/appStore";
import type { BlockEntry, MaskParamSpec } from "../types/api";

interface ParameterPanelProps {
  modelId: string;
}

export function ParameterPanel({ modelId: _modelId }: ParameterPanelProps): JSX.Element {
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

  if (!selectedNodeId) {
    return (
      <div
        data-testid="parameter-panel-empty"
        className="border-l border-gray-200 bg-white p-3 text-xs text-gray-500"
      >
        {t("inspector.empty")}
      </div>
    );
  }
  if (!block) {
    return (
      <div
        data-testid="parameter-panel-not-found"
        className="border-l border-gray-200 bg-white p-3 text-xs text-red-600"
      >
        {t("inspector.not_found", { id: selectedNodeId })}
      </div>
    );
  }

  // ADR-0021 §(9): mask_params が宣言された Subsystem は mask 値編集モードに切替
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
// 通常 block の数値 inline 編集 (Phase 2 互換、editingModel に書き込む)
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

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const prevBlockIdRef = useRef<string | undefined>(undefined);

  // ブロック切替時に draft を最新値で初期化 (number/string/bool すべてを文字列化して保持)
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
  const shortType = block.type.split(".").at(-1) ?? block.type;
  // ADR-0039 follow-up (v0.15.0 / code-reviewer SHOULD): registry の block meta は
  // ループ外で 1 度だけ取得 (= ループ内毎回 lookup を避ける + 意図を明確化)。
  const blockMeta = registryMap.get(block.type);

  const commit = (k: string, raw: string, originalType: string): void => {
    let newValue: unknown;
    if (originalType === "number") {
      const parsed = parseNumericInput(raw);
      if (parsed === null) {
        setError(t("inspector.invalid_number", { name: k }));
        return;
      }
      // n_inputs / n / n_outputs などの整数 param は明示的に整数化
      const isIntParam =
        k === "n" ||
        k === "n_inputs" ||
        k === "n_outputs" ||
        k === "decimals" ||
        k === "port_idx";
      newValue = isIntParam ? Math.trunc(parsed) : parsed;
    } else if (originalType === "boolean") {
      newValue = raw === "true";
    } else {
      // string param (e.g. Sum.signs, Switch.criterion)
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
      className="flex h-full flex-col gap-2 p-3 text-xs"
    >
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 pb-2">
        <h3 className="truncate text-sm font-semibold text-slate-800">
          {block.id}
        </h3>
        <span
          title={block.type}
          className="truncate font-mono text-[10px] text-slate-500"
        >
          {shortType}
        </span>
      </div>

      {editableEntries.length === 0 && (
        <div className="text-slate-500">
          {t("inspector.no_editable")}
        </div>
      )}

      {editableEntries.map(([k, v]) => {
        const valueType = typeof v;
        // ADR-0039 follow-up (v0.15.0): registry の enum_values を見て、許容値が
        // 限定された string param は ``<select>`` で render する (= MinMax の
        // operator、Switch の criterion、Logical/Relational の operator 等)。
        const enumValues = blockMeta?.params_spec.find((p) => p.name === k)?.enum_values;
        return (
          <label key={k} className="flex flex-col gap-0.5">
            <span className="flex items-center justify-between text-slate-700">
              <span className="font-medium">{k}</span>
              <span className="font-mono text-[9px] text-slate-400">
                {valueType}
              </span>
            </span>
            {enumValues && enumValues.length > 0 ? (
              <select
                data-testid={`param-input-${k}`}
                value={draft[k] ?? String(v)}
                onChange={(e) => {
                  setDraft((prev) => ({ ...prev, [k]: e.target.value }));
                  commit(k, e.target.value, "string");
                }}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="false">false</option>
                <option value="true">true</option>
              </select>
            ) : valueType === "number" ? (
              <input
                type="number"
                inputMode="decimal"
                step="any"
                data-testid={`param-input-${k}`}
                value={draft[k] ?? ""}
                onChange={(e) => {
                  const val = e.target.value;
                  setDraft((prev) => ({ ...prev, [k]: val }));
                  // 入力途中でも有効な数値なら即 commit (= canvas 表示が live 更新される)
                  if (val !== "" && parseNumericInput(val) !== null) {
                    commit(k, val, "number");
                  }
                }}
                onBlur={(e) => commit(k, e.target.value, "number")}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            ) : (
              <input
                type="text"
                data-testid={`param-input-${k}`}
                value={draft[k] ?? ""}
                onChange={(e) => {
                  const val = e.target.value;
                  setDraft((prev) => ({ ...prev, [k]: val }));
                  // 任意の文字列でも即 commit (空でも OK)。Sum.signs / Switch.criterion 等の
                  // ライブ反映用 (ハンドル数が ``signs.length`` で変わる)。
                  commit(k, val, "string");
                }}
                onBlur={(e) => commit(k, e.target.value, "string")}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            )}
          </label>
        );
      })}

      {readOnlyEntries.length > 0 && (
        <details className="mt-2 rounded border border-slate-200 p-2">
          <summary className="cursor-pointer text-slate-600">
            {t("inspector.read_only_summary", {
              count: readOnlyEntries.length,
            })}
          </summary>
          <pre className="mt-1 overflow-auto text-[10px] text-slate-700">
            {readOnlyJson}
          </pre>
        </details>
      )}

      {error && <div className="text-rose-600">{error}</div>}
      <div className="mt-2 text-[10px] text-slate-400">
        {t("inspector.autosave_hint")}
      </div>
    </div>
  );
}

function formatForDraft(v: number | string | boolean): string {
  if (typeof v === "boolean") return v ? "true" : "false";
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

  const commit = (name: string, raw: string, type: MaskParamSpec["type"]): void => {
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
              ? (typeof p.default === "number" ? p.default : 0)
              : (p.type === "int" ? Math.trunc(existingNum) : existingNum);
        }
      }
    }
    updateSubsystemMaskValues(block.id, next);
  };

  const shortType = block.type.split(".").at(-1) ?? block.type;

  return (
    <div
      data-testid="parameter-panel-mask"
      className="flex h-full flex-col gap-2 border-l border-gray-200 bg-white p-3 text-xs"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-sm font-medium">{block.id}</h3>
        <span
          title={block.type}
          className="truncate font-mono text-[10px] text-gray-500"
        >
          {shortType} · {t("inspector.mask.suffix")}
        </span>
      </div>

      <div className="text-[10px] text-gray-500">
        {t("inspector.mask.section_hint")}
      </div>

      {maskParams.map((p) => (
        <label key={p.name} className="flex flex-col gap-1">
          <span className="text-gray-700">
            {p.name}{" "}
            <span className="text-[10px] text-gray-400">({p.type})</span>
          </span>
          {p.type === "bool" ? (
            <select
              data-testid={`mask-input-${p.name}`}
              value={draft[p.name] ?? "false"}
              onChange={(e) => {
                // ADR-0021 code-reviewer SHOULD: select は onChange で commit
                // (onBlur だと数値 fields の不正値 evaluation が誘発される)
                setDraft((prev) => ({ ...prev, [p.name]: e.target.value }));
                commit(p.name, e.target.value, p.type);
              }}
              className="rounded border border-gray-300 px-2 py-1 text-sm"
            >
              <option value="false">false</option>
              <option value="true">true</option>
            </select>
          ) : (
            <input
              type="number"
              inputMode={p.type === "int" ? "numeric" : "decimal"}
              step={p.type === "int" ? "1" : "any"}
              data-testid={`mask-input-${p.name}`}
              value={draft[p.name] ?? ""}
              onChange={(e) => {
                const val = e.target.value;
                setDraft((prev) => ({ ...prev, [p.name]: val }));
                // 有効な数値なら即 commit (= live 反映)
                if (val !== "" && parseNumericInput(val) !== null) {
                  commit(p.name, val, p.type);
                }
              }}
              onBlur={(e) => commit(p.name, e.target.value, p.type)}
              className="rounded border border-gray-300 px-2 py-1 text-sm"
            />
          )}
          {p.description && (
            <span className="text-[10px] text-gray-500">{p.description}</span>
          )}
        </label>
      ))}

      {error && <div className="text-red-600">{error}</div>}
      <div className="mt-2 text-[10px] text-gray-400">
        {t("inspector.mask.autosave_hint")}
      </div>
    </div>
  );
}
