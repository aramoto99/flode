// SPEC-0023 / ADR-0073: PythonFunction 専用の Inspector 編集 UI。
//
// 構成 (ParameterPanel の 3 つ目の分岐):
//   * STRUCTURE: introspect の結果を read-only 表示 (コードが SSOT、Inspector では
//     編集できない = SPEC 確定事項 C)
//   * CODE: 既存 ExpressionEditor (blur で commit) + 「編集...」→ PythonCodeDialog
//   * PARAMETERS: コードの keyword-only 引数から **動的生成** した行 (float/int →
//     数値、bool → select、str → text)。値は ``params.user_params`` に保存
//
// コードの commit は必ず introspect を通し、解析に失敗したら params を更新しない
// (= 壊れたコードでポート数が崩れない)。サーバは exec しない。

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { parseNumericInput } from "../lib/paramEdit";
import { indexRegistry } from "../lib/portShapeValidate";
import {
  ensurePythonSpecs,
  getCachedPythonSpec,
  introspectSingle,
} from "../lib/pythonFunctionSpec";
import { usePythonSpecVersion } from "../lib/usePythonSpecVersion";
import { updateBlockParams } from "../store/appStore";
import type { BlockEntry, BlockParamSpec, PythonFunctionSpec } from "../types/api";
import { PythonCodeDialog } from "./PythonCodeDialog";
import {
  ExpressionEditor,
  INPUT_CLS,
  INPUT_MONO_CLS,
  PropertyGrid,
  PropertyHint,
  PropertyRow,
  SecondaryButton,
  SectionDivider,
  SELECT_CLS,
} from "./ui/inspector";

const LABEL_W = 88;

function _userParams(block: BlockEntry): Record<string, unknown> {
  const up = block.params.user_params;
  return up && typeof up === "object" && !Array.isArray(up)
    ? (up as Record<string, unknown>)
    : {};
}

function _isNumericType(p: BlockParamSpec): boolean {
  return p.type === "float" || p.type === "int" || p.type === "float64";
}

export function PythonFunctionEditor({
  block,
  header,
}: {
  block: BlockEntry;
  header: React.ReactNode;
}): JSX.Element {
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

  const code = typeof block.params.code === "string" ? block.params.code : "";
  usePythonSpecVersion();
  const cached = getCachedPythonSpec(code);
  useEffect(() => {
    if (code !== "" && cached === undefined) void ensurePythonSpecs([code]);
  }, [code, cached]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [paramError, setParamError] = useState<string | null>(null);

  const commitParams = useCallback(
    (next: Record<string, unknown>) => {
      updateBlockParams(block.id, { ...block.params, ...next }, registryMap);
    },
    [block.id, block.params, registryMap],
  );

  /** コード変更の唯一の経路: introspect → 成功時のみ params 更新。 */
  const applyCode = useCallback(
    (nextCode: string, spec?: PythonFunctionSpec): void => {
      if (nextCode === code) return;
      const finish = (s: PythonFunctionSpec): void => {
        // 新コードで宣言されなくなった user_params は落とす (= backend と同じ規則)
        const declared = new Set(s.params_spec.map((p) => p.name));
        const kept: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(_userParams(block))) {
          if (declared.has(k)) kept[k] = v;
        }
        setCodeError(null);
        commitParams({ code: nextCode, user_params: kept });
      };
      if (spec !== undefined) {
        finish(spec);
        return;
      }
      void introspectSingle(nextCode)
        .then((r) => {
          if (!r.resolved) {
            const { lineno, message } = r.error;
            setCodeError(
              lineno !== null
                ? t("python_function.dialog.error_at", { lineno, message })
                : message,
            );
            return;
          }
          finish(r);
        })
        .catch((e: unknown) => {
          setCodeError(
            t("python_function.dialog.network_error", {
              message: e instanceof Error ? e.message : String(e),
            }),
          );
        });
    },
    [block, code, commitParams, t],
  );

  const userParams = _userParams(block);
  const spec = cached !== undefined && cached.resolved ? cached : null;
  const specError = cached !== undefined && !cached.resolved ? cached.error : null;

  const commitUserParam = (p: BlockParamSpec, raw: string): void => {
    let value: unknown;
    if (_isNumericType(p)) {
      const parsed = parseNumericInput(raw);
      if (parsed === null) {
        setParamError(t("inspector.invalid_number", { name: p.name }));
        return;
      }
      value = p.type === "int" ? Math.trunc(parsed) : parsed;
    } else if (p.type === "bool") {
      value = raw === "true";
    } else {
      value = raw;
    }
    setParamError(null);
    commitParams({ user_params: { ...userParams, [p.name]: value } });
  };

  const sampleTimeLabel = (st: number | null): string => {
    if (st === null || st === 0) return t("python_function.sample_time.continuous");
    if (st === -1) return t("python_function.sample_time.inherited");
    return String(st);
  };

  return (
    <div
      data-testid="parameter-panel"
      className="flex h-full flex-col bg-white text-[11px]"
    >
      {header}
      <div className="flex flex-1 flex-col overflow-y-auto px-3 py-2">
        <PropertyGrid>
          <SectionDivider label={t("python_function.section.structure")} />
          {spec !== null ? (
            <>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.function")}>
                <span className="font-mono" data-testid="pf-func-name">{spec.func_name}()</span>
              </PropertyRow>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.inputs")}>
                <span className="font-mono" data-testid="pf-n-inputs">{spec.n_inputs}</span>
              </PropertyRow>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.outputs")}>
                <span className="font-mono" data-testid="pf-n-outputs">{spec.n_outputs}</span>
              </PropertyRow>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.states")}>
                <span className="font-mono">{spec.n_states}</span>
              </PropertyRow>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.sample_time")}>
                <span className="font-mono">{sampleTimeLabel(spec.sample_time)}</span>
              </PropertyRow>
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.feedthrough")}>
                <span className="font-mono">{spec.direct_feedthrough ? "true" : "false"}</span>
              </PropertyRow>
            </>
          ) : specError !== null ? (
            <div
              role="alert"
              data-testid="pf-spec-error"
              className="border border-rose-300 bg-rose-50 px-2 py-1 font-mono text-[10px] text-rose-700 whitespace-pre-wrap"
            >
              {t("python_function.analysis_failed")}
              {"\n"}
              {specError.lineno !== null
                ? t("python_function.dialog.error_at", {
                    lineno: specError.lineno,
                    message: specError.message,
                  })
                : specError.message}
            </div>
          ) : (
            <div className="px-2 py-1 text-slate-500" data-testid="pf-analysing">
              {t("python_function.analysing")}
            </div>
          )}

          <SectionDivider label={t("python_function.section.code")} />
          <ExpressionEditor
            value={code}
            testid="pf-code-inline"
            onCommit={(next) => applyCode(next)}
            maxRows={12}
            widthClass="min-w-0 flex-1"
          />
          <div className="flex justify-end py-1">
            <SecondaryButton onClick={() => setDialogOpen(true)} testId="pf-code-edit">
              {t("python_function.edit")}
            </SecondaryButton>
          </div>
          {codeError !== null && (
            <div
              role="alert"
              data-testid="pf-code-error"
              className="border border-rose-300 bg-rose-50 px-2 py-1 font-mono text-[10px] text-rose-700 whitespace-pre-wrap"
            >
              {codeError}
            </div>
          )}
          <PropertyHint labelWidth={0} text={t("python_function.security_hint")} />

          <SectionDivider label={t("python_function.section.parameters")} />
          {spec !== null && spec.params_spec.length === 0 && (
            <div className="px-2 py-1 text-slate-500">{t("python_function.no_params")}</div>
          )}
          {spec !== null &&
            spec.params_spec.map((p) => {
              const current = userParams[p.name] ?? (p.has_default ? p.default : undefined);
              const testId = `pf-param-${p.name}`;
              if (p.type === "bool") {
                return (
                  <PropertyRow key={p.name} labelWidth={LABEL_W} labelAlign="left" label={p.name}>
                    <select
                      data-testid={testId}
                      value={current === true ? "true" : "false"}
                      onChange={(e) => commitUserParam(p, e.target.value)}
                      className={`${SELECT_CLS} min-w-0 w-24`}
                    >
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  </PropertyRow>
                );
              }
              return (
                <PropertyRow key={p.name} labelWidth={LABEL_W} labelAlign="left" label={p.name}>
                  <UserParamInput
                    spec={p}
                    value={current}
                    testId={testId}
                    placeholder={!p.has_default ? t("python_function.required") : ""}
                    onCommit={(raw) => commitUserParam(p, raw)}
                  />
                </PropertyRow>
              );
            })}
          {paramError !== null && (
            <div
              role="alert"
              className="mt-2 border border-rose-300 bg-rose-50 px-2 py-1 text-[11px] text-rose-700"
            >
              {paramError}
            </div>
          )}
        </PropertyGrid>
      </div>
      <div className="border-t border-slate-200 bg-slate-50 px-3 py-1 text-[10px] text-slate-500">
        {t("inspector.autosave_hint")}
      </div>
      {dialogOpen && (
        <PythonCodeDialog
          initialCode={code}
          onApply={(nextCode, s) => {
            setDialogOpen(false);
            applyCode(nextCode, s);
          }}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </div>
  );
}

/** 数値 / 文字列パラメータの text 入力 (draft を持ち、blur / 有効値で commit)。 */
function UserParamInput({
  spec,
  value,
  testId,
  placeholder,
  onCommit,
}: {
  spec: BlockParamSpec;
  value: unknown;
  testId: string;
  placeholder: string;
  onCommit: (raw: string) => void;
}): JSX.Element {
  const numeric = _isNumericType(spec);
  const display = value === undefined || value === null ? "" : String(value);
  const [draft, setDraft] = useState<string>(display);
  useEffect(() => {
    setDraft(display);
  }, [display]);
  return (
    <input
      type="text"
      inputMode={numeric ? "decimal" : undefined}
      data-testid={testId}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => {
        const v = e.target.value;
        setDraft(v);
        if (!numeric) onCommit(v);
        else if (v !== "" && parseNumericInput(v) !== null) onCommit(v);
      }}
      onBlur={(e) => {
        if (e.target.value !== "" || !numeric) onCommit(e.target.value);
      }}
      className={`${numeric ? INPUT_MONO_CLS : INPUT_CLS} min-w-0 flex-1 max-w-[140px]`}
    />
  );
}
