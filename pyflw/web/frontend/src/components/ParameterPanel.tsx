// ノードのパラメータ inline 編集パネル (ADR-0012 §(3)、ADR-0019 §(5) auto-save 連動、
// ADR-0021 §(9) で Subsystem の mask_values 編集モードを追加)。
//
// editingModel + editingPath が source of truth。useAutoSave がそれを PUT する。

import { useEffect, useMemo, useRef, useState } from "react";

import { findBlockAtPath } from "../lib/pathResolver";
import {
  isEditableParam,
  parseNumericInput,
} from "../lib/paramEdit";
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
        Click a block in the diagram to edit its parameters.
      </div>
    );
  }
  if (!block) {
    return (
      <div
        data-testid="parameter-panel-not-found"
        className="border-l border-gray-200 bg-white p-3 text-xs text-red-600"
      >
        Block {selectedNodeId} not found in current scope.
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
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const prevBlockIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (block.id === prevBlockIdRef.current) return;
    prevBlockIdRef.current = block.id;
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(block.params)) {
      if (isEditableParam(v)) next[k] = String(v);
    }
    setDraft(next);
    setError(null);
  }, [block]);

  const allEntries = Object.entries(block.params);
  const editableEntries = allEntries.filter(([, v]) => isEditableParam(v));
  const readOnlyEntries = allEntries.filter(([, v]) => !isEditableParam(v));
  const readOnlyJson = useMemo(
    () => JSON.stringify(Object.fromEntries(readOnlyEntries), null, 2),
    [readOnlyEntries],
  );
  const shortType = block.type.split(".").at(-1) ?? block.type;

  const commit = (k: string, raw: string): void => {
    const parsed = parseNumericInput(raw);
    if (parsed === null) {
      setError(`Invalid number for "${k}"`);
      return;
    }
    setError(null);
    updateBlockParams(block.id, { ...block.params, [k]: parsed });
  };

  return (
    <div
      data-testid="parameter-panel"
      className="flex h-full flex-col gap-2 border-l border-gray-200 bg-white p-3 text-xs"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-sm font-medium">{block.id}</h3>
        <span
          title={block.type}
          className="truncate font-mono text-[10px] text-gray-500"
        >
          {shortType}
        </span>
      </div>

      {editableEntries.length === 0 && (
        <div className="text-gray-500">
          No editable numeric parameters on this block.
        </div>
      )}

      {editableEntries.map(([k]) => (
        <label key={k} className="flex flex-col gap-1">
          <span className="text-gray-700">{k}</span>
          <input
            type="number"
            inputMode="decimal"
            step="any"
            data-testid={`param-input-${k}`}
            value={draft[k] ?? ""}
            onChange={(e) =>
              setDraft((prev) => ({ ...prev, [k]: e.target.value }))
            }
            onBlur={(e) => commit(k, e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
      ))}

      {readOnlyEntries.length > 0 && (
        <details className="mt-2 rounded border border-gray-200 p-2">
          <summary className="cursor-pointer text-gray-600">
            Other parameters ({readOnlyEntries.length}, read-only)
          </summary>
          <pre className="mt-1 overflow-auto text-[10px] text-gray-700">
            {readOnlyJson}
          </pre>
        </details>
      )}

      {error && <div className="text-red-600">{error}</div>}
      <div className="mt-2 text-[10px] text-gray-400">
        Edits auto-save (debounce 500 ms or Ctrl+S).
      </div>
    </div>
  );
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
        setError(`Invalid number for "${name}"`);
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
          {shortType} · mask
        </span>
      </div>

      <div className="text-[10px] text-gray-500">
        Mask parameters (declared on the Subsystem). Editing here updates the
        inner block placeholders on save.
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
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, [p.name]: e.target.value }))
              }
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
        Mask edits auto-save. Double-click the Subsystem to drill into its
        internal diagram.
      </div>
    </div>
  );
}
