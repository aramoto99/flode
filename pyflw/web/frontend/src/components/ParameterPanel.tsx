// ノードのパラメータ inline 編集パネル (ADR-0012 §(3))。
//
// ADR-0012 §(10) で当初 Phase 3 送りとしていたが、Phase 2 改善 #4 として
// 数値パラメータの inline 編集だけを先行実装する。
//
// スコープ:
// - 数値 (number) パラメータのみ inline 編集
// - その他 (list / object / string / boolean / null) は JSON read-only 表示
// - 保存は ``PUT /api/v1/models/{id}`` (REST API、ADR-0011)
// - 保存後に React Query の ``["model", id]`` を invalidate して最新を再取得

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { getModel, updateModel } from "../api/client";
import {
  findBlock,
  isEditableParam,
  parseNumericInput,
  updateBlockParam,
} from "../lib/paramEdit";
import { useAppStore } from "../store/appStore";

interface ParameterPanelProps {
  modelId: string;
}

export function ParameterPanel({ modelId }: ParameterPanelProps): JSX.Element {
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const queryClient = useQueryClient();

  const { data: model, isFetching } = useQuery({
    queryKey: ["model", modelId],
    queryFn: () => getModel(modelId),
  });

  const mutation = useMutation({
    mutationFn: ({ payload }: { payload: Parameters<typeof updateModel>[1] }) =>
      updateModel(modelId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model", modelId] });
    },
  });

  // ローカル編集状態 (ノード切替時のみ初期化、model 再取得では上書きしない)
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const prevBlockIdRef = useRef<string | undefined>(undefined);

  const block = model && selectedNodeId ? findBlock(model, selectedNodeId) : undefined;
  // 現在の block.id が直前 render の prevBlockIdRef と異なれば「新ブロック」=
  // draft を初期化、mutation 状態 (Saved badge) もリセット対象とする。
  const blockChanged = block?.id !== prevBlockIdRef.current;

  // ブロック切替時のみ draft を最新値に同期する。同一ブロックの model 再取得
  // (PUT 後の invalidateQueries) では draft を維持し、ユーザーの編集中入力を
  // 上書きしない (code-reviewer MUST 修正)。
  useEffect(() => {
    if (!block) {
      prevBlockIdRef.current = undefined;
      setDraft({});
      setError(null);
      return;
    }
    if (block.id === prevBlockIdRef.current) return;
    prevBlockIdRef.current = block.id;
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(block.params)) {
      if (isEditableParam(v)) next[k] = String(v);
    }
    setDraft(next);
    setError(null);
  }, [block]);

  // ブロック切替時に mutation の Saved/Error 表示をクリア。useEffect での副作用は
  // 上の draft 同期と独立させ、初期 render 時に余計な mutation.reset() が走らない
  // ようにする (code-reviewer SHOULD 修正)。
  useEffect(() => {
    if (blockChanged) mutation.reset();
    // mutation.reset の identity 変化で無限ループしないよう deps から除外
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockChanged]);

  // params の分類と read-only JSON memo は早期 return より前で計算する
  // (Rules of Hooks: useMemo は条件付き return の後に置けない)。
  const allEntries = block ? Object.entries(block.params) : [];
  const editableEntries = allEntries.filter(([, v]) => isEditableParam(v));
  const readOnlyEntries = allEntries.filter(([, v]) => !isEditableParam(v));
  // 大きな行列パラメータ (DiscreteStateSpace 等) を毎 render で stringify すると重い
  // ため memoize する (code-reviewer SHOULD 修正)。
  const readOnlyJson = useMemo(
    () => JSON.stringify(Object.fromEntries(readOnlyEntries), null, 2),
    [readOnlyEntries],
  );

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
        Block {selectedNodeId} not found in model.
      </div>
    );
  }

  // ブロック type の末尾 class 名を表示用に切り出す。完全名は title 属性で tooltip に
  const shortType = block.type.split(".").at(-1) ?? block.type;

  const onSave = (): void => {
    if (!model) return;
    // 全 editable param を validate
    const newParams: Record<string, number> = {};
    for (const [k] of editableEntries) {
      const parsed = parseNumericInput(draft[k] ?? "");
      if (parsed === null) {
        setError(`Invalid number for "${k}"`);
        return;
      }
      newParams[k] = parsed;
    }
    setError(null);

    // 1 ブロック分すべてのパラメータをまとめて新モデルに反映
    let nextModel = model;
    for (const [k, v] of Object.entries(newParams)) {
      nextModel = updateBlockParam(nextModel, block.id, k, v);
    }
    mutation.mutate({ payload: nextModel });
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

      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          // ``isPending`` (PUT 中) に加え ``isFetching`` (invalidate 後の再取得中) も
          // disabled に含めることで、Save 連打による並走 PUT を防止する
          // (code-reviewer MUST 修正)。
          disabled={
            mutation.isPending || isFetching || editableEntries.length === 0
          }
          data-testid="parameter-panel-save"
          className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white disabled:bg-gray-400"
        >
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
        {mutation.isSuccess && !isFetching && (
          <span className="text-green-700">Saved</span>
        )}
        {mutation.isError && (
          <span className="text-red-600">
            {mutation.error instanceof Error
              ? mutation.error.message
              : "An error occurred"}
          </span>
        )}
      </div>
    </div>
  );
}
