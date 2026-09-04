// SPEC-0023 / SPEC-0024 / ADR-0073 / ADR-0074: PythonFunction 専用の Inspector 編集 UI。
//
// 構成 (ParameterPanel の 3 つ目の分岐):
//   * STRUCTURE: 入力 / 出力を NumberInput で編集可能 (SPEC-0024: 値の commit は
//     サーバの rewrite endpoint がコードを書き換える = SSOT はコードのまま)。
//     関数名 / 状態数 / sample_time / 直達は従来どおり read-only
//   * PORT NAMES: ポートごとの TextInput (maxLength 32、空 = 無名)
//   * CODE: 既存 ExpressionEditor (blur で commit) + 「編集...」→ PythonCodeDialog
//   * PARAMETERS: コードの keyword-only 引数から動的生成した行 + 構造編集
//     (SPEC-0025: 追加 / 削除 / rename。rename は user_params の key も
//     pruning より前に追随させる)
//
// 競合制御 (ADR-0074 §論点 7): rewrite は in-flight 中 disabled + リクエストに使った
// base code が現在の code と一致するときだけ適用 + 世代 (seq) が古い応答は破棄。
// commit の順序は rewrite → putPythonSpec → applyCode (剪定ガードを満たす、V14)。

import { useQuery } from "@tanstack/react-query";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata, rewritePythonFunction } from "../api/client";
import { parseNumericInput } from "../lib/paramEdit";
import { indexRegistry } from "../lib/portShapeValidate";
import {
  ensurePythonSpecs,
  getCachedPythonSpec,
  introspectSingle,
  putPythonSpec,
} from "../lib/pythonFunctionSpec";
import { findBlockAtPath } from "../lib/pathResolver";
import { usePythonSpecVersion } from "../lib/usePythonSpecVersion";
import { updateBlockParams, useAppStore } from "../store/appStore";
import type {
  BlockEntry,
  BlockParamSpec,
  PythonFunctionParamEdit,
  PythonFunctionSpec,
} from "../types/api";
import { PythonCodeDialog } from "./PythonCodeDialog";
import {
  ExpressionEditor,
  INPUT_CLS,
  INPUT_MONO_CLS,
  NumberInput,
  PropertyGrid,
  PropertyHint,
  PropertyRow,
  RowActionButton,
  SecondaryButton,
  SectionDivider,
  SELECT_CLS,
  TextInput,
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

/** 空文字 padding でポート数分の名前配列にする (SPEC-0024 N3 の UI 側)。 */
function _paddedNames(names: readonly string[] | undefined, count: number): string[] {
  const base = names ?? [];
  return Array.from({ length: count }, (_, i) => base[i] ?? "");
}

/** SPEC-0025: パラメータ名 rename の draft (元名 → 表示中の名前)。 */
function _paramNameDrafts(
  spec: { params_spec: { name: string }[] } | null | undefined,
): Record<string, string> {
  return Object.fromEntries((spec?.params_spec ?? []).map((p) => [p.name, p.name]));
}

// SPEC-0025 P1〜P4 のクライアント側検証。**権威はサーバ** (route の 400 と engine の
// 二重ゲート) で、ここは往復を減らすためだけの写し。ずれてもサーバが正しく拒否する。
const PARAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const MAX_PARAM_NAME_LEN = 64;
const MAX_PARAMS = 32;
// Python の hard keyword (soft keyword の match / case / type / _ は許可 = P3)
const PY_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break",
  "class", "continue", "def", "del", "elif", "else", "except", "finally", "for",
  "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
  "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

function _validParamName(name: string): boolean {
  return (
    PARAM_NAME_RE.test(name) && !PY_KEYWORDS.has(name) && name.length <= MAX_PARAM_NAME_LEN
  );
}

type ParamTypeName = "float" | "int" | "bool" | "str";
const PARAM_TYPE_OPTIONS: readonly ParamTypeName[] = ["float", "int", "bool", "str"];
/** サーバ `MAX_PARAM_INT_DEFAULT_DIGITS` の写し。 */
const MAX_PARAM_INT_DIGITS = 32;

/** str→数値のパースを Python (`int(v, 10)` / `float(v)`) の受理文法に寄せる
 *  (code-reviewer SHOULD: `Number()` は 0x/0o/0b を受理し、PEP 515 の
 *  アンダースコア区切りを拒否するため規則がずれる)。 */
function _parseNumberLikePython(s: string): number | undefined {
  const t = s.trim();
  if (t === "") return undefined;
  if (/^[+-]?0[xob]/i.test(t)) return undefined; // Python の float()/int(,10) は拒否
  if (
    t.includes("_") &&
    !/^[+-]?\d(?:_?\d)*(?:\.\d(?:_?\d)*)?(?:[eE][+-]?\d(?:_?\d)*)?$/.test(t)
  ) {
    return undefined; // アンダースコアは数字の間のみ (PEP 515)
  }
  const n = Number(t.replace(/_/g, ""));
  return Number.isFinite(n) ? n : undefined;
}

/** SPEC-0025 Amendment: 型変更時の設定値 (user_params) の変換。
 *  サーバの `_convert_param_value` と同一規則 (**変えるときは両方変える**)。
 *  `source` は変換前の宣言型 (float→str の `.0` 付与 = Python repr の再現に使う)。
 *  変換できなければ undefined = キーを落とし、新しいコード側 default に任せる。 */
function _convertUserParamValue(
  v: unknown,
  target: ParamTypeName,
  source: string | null,
): unknown | undefined {
  if (target === "bool") return typeof v === "boolean" ? v : undefined;
  if (target === "float") {
    if (typeof v === "boolean") return undefined;
    if (typeof v === "number") return Number.isFinite(v) ? v : undefined;
    if (typeof v === "string") return _parseNumberLikePython(v);
    return undefined;
  }
  if (target === "int") {
    if (typeof v === "boolean") return undefined;
    let n: number | undefined;
    if (typeof v === "number") n = Number.isFinite(v) ? v : undefined;
    else if (typeof v === "string") n = _parseNumberLikePython(v);
    if (n === undefined) return undefined;
    const out = Math.trunc(n);
    return String(Math.abs(out)).length <= MAX_PARAM_INT_DIGITS ? out : undefined;
  }
  // str
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return undefined;
    let text = String(v);
    // Python repr(float) の再現: 整数値の float は ".0" を付ける (source が float のとき)
    if (source === "float" && !/[.eE]/.test(text)) text += ".0";
    return text;
  }
  return undefined;
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
  const [structError, setStructError] = useState<string | null>(null);

  // SPEC-0024 競合制御: in-flight lock + 世代カウンタ
  const [rewriteBusy, setRewriteBusy] = useState(false);
  const rewriteSeq = useRef(0);
  const codeRef = useRef(code);
  codeRef.current = code;
  const composingRef = useRef(false);

  /** ストア上の **現在の** コード (ADR-0074 §論点 7 base 一致検証)。
   *  prop (`codeRef`) は再レンダ前の値でありうるため、応答適用の判定は
   *  live 値と比較する (再レンダ前に応答が着くレースを塞ぐ)。 */
  const liveCode = useCallback((): string => {
    const s = useAppStore.getState();
    try {
      const live = s.editingModel
        ? findBlockAtPath(s.editingModel, s.editingPath, block.id)
        : undefined;
      const c = live?.params.code;
      return typeof c === "string" ? c : codeRef.current;
    } catch {
      return codeRef.current;
    }
  }, [block.id]);

  const spec = cached !== undefined && cached.resolved ? cached : null;
  const specError = cached !== undefined && !cached.resolved ? cached.error : null;
  const editable = spec?.editable;

  // STRUCTURE / PORT NAMES の draft (spec 変化 = 外部からのコード変更でリセット)
  const [draftInputs, setDraftInputs] = useState<number | undefined>(undefined);
  const [draftOutputs, setDraftOutputs] = useState<number | undefined>(undefined);
  const [draftInNames, setDraftInNames] = useState<string[]>([]);
  const [draftOutNames, setDraftOutNames] = useState<string[]>([]);
  const [draftParamNames, setDraftParamNames] = useState<Record<string, string>>({});
  // SPEC-0025: 追加行 (型 / 名前 / 既定値) の draft
  const [addName, setAddName] = useState("");
  const [addType, setAddType] = useState<"float" | "int" | "bool" | "str">("float");
  const [addDefault, setAddDefault] = useState("0");
  useEffect(() => {
    setDraftInputs(spec?.n_inputs);
    setDraftOutputs(spec?.n_outputs);
    setDraftInNames(_paddedNames(spec?.input_names, spec?.n_inputs ?? 0));
    setDraftOutNames(_paddedNames(spec?.output_names, spec?.n_outputs ?? 0));
    setDraftParamNames(_paramNameDrafts(spec));
    setStructError(null);
  }, [spec]);

  const commitParams = useCallback(
    (next: Record<string, unknown>) => {
      updateBlockParams(block.id, { ...block.params, ...next }, registryMap);
    },
    [block.id, block.params, registryMap],
  );

  /** rewrite 成功時の共通 commit: 宣言から消えた user_params を落として保存。
   *  ``userParamsOverride`` は rename の key 追随用 (SPEC-0025 §7: **pruning より
   *  前に**差し替えないと、rename 直後に値が静かに消える)。 */
  const finishApply = useCallback(
    (
      nextCode: string,
      s: PythonFunctionSpec,
      userParamsOverride?: Record<string, unknown>,
    ): void => {
      const declared = new Set(s.params_spec.map((p) => p.name));
      const kept: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(userParamsOverride ?? _userParams(block))) {
        if (declared.has(k)) kept[k] = v;
      }
      setCodeError(null);
      commitParams({ code: nextCode, user_params: kept });
    },
    [block, commitParams],
  );

  /** コード全文の変更経路 (inline editor / dialog): introspect 成功時のみ commit。 */
  const applyCode = useCallback(
    (nextCode: string, s?: PythonFunctionSpec): void => {
      if (nextCode === code) return;
      if (s !== undefined) {
        finishApply(nextCode, s);
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
          finishApply(nextCode, r);
        })
        .catch((e: unknown) => {
          setCodeError(
            t("python_function.dialog.network_error", {
              message: e instanceof Error ? e.message : String(e),
            }),
          );
        });
    },
    [code, finishApply, t],
  );

  /** 失敗 / 破棄時に draft を現行コードの spec へ戻す (ADR-0074: 値ロールバック)。 */
  const rollbackDrafts = useCallback((): void => {
    const current = getCachedPythonSpec(codeRef.current);
    if (current === undefined || !current.resolved) return;
    setDraftInputs(current.n_inputs);
    setDraftOutputs(current.n_outputs);
    setDraftInNames(_paddedNames(current.input_names, current.n_inputs));
    setDraftOutNames(_paddedNames(current.output_names, current.n_outputs));
    setDraftParamNames(_paramNameDrafts(current));
  }, []);

  /** SPEC-0024/0025: 構造編集の唯一の commit 経路 (rewrite → putPythonSpec → applyCode)。
   *  ポート編集とパラメータ編集は**同じ in-flight lock / seq / base 一致検証を
   *  共有**する (どちらも params.code を書き換えるため。SPEC-0025 §6-6)。 */
  const commitRewrite = useCallback(
    (
      edits: {
        inputs?: number;
        outputs?: number;
        input_names?: string[];
        output_names?: string[];
        params?: PythonFunctionParamEdit[];
      },
      opts?: {
        /** rename 時の user_params key 追随 (pruning より前に差し替える)。 */
        renameParam?: { from: string; to: string };
        /** retype 時の user_params 値の変換 (変換できなければキーを落とす)。
         *  `from` = 変換前の宣言型 (float→str の ".0" 再現に使う)。 */
        retypeParam?: { name: string; type: ParamTypeName; from: string | null };
        /** applied:true で commit した直後に呼ぶ (追加行のクリア等)。 */
        onApplied?: () => void;
      },
    ): void => {
      if (rewriteBusy) return;
      const baseCode = codeRef.current;
      const seq = ++rewriteSeq.current;
      setRewriteBusy(true);
      setStructError(null);
      void rewritePythonFunction(baseCode, edits)
        .then((resp) => {
          if (seq !== rewriteSeq.current) return; // 古い応答は破棄
          if (liveCode() !== baseCode) {
            // 編集中に別経路でコードが変わった → 適用せず破棄 (base 一致検証)
            setStructError(t("python_function.rewrite_stale"));
            rollbackDrafts();
            return;
          }
          if (!resp.applied) {
            const { lineno, message } = resp.error;
            const prefixed = lineno !== null ? `L${lineno}: ${message}` : message;
            // SPEC-0025 §8: rename の拒否 (U1〜U8 / 名前衝突等、kind=unsupported) は
            // 「コードで直す」案内付きのローカライズ文で出す (wire に reason は無い
            // ため原因別の文面はサーバ message の併記で代替)
            setStructError(
              opts?.renameParam !== undefined && resp.error.kind === "unsupported"
                ? t("python_function.params.rename_unsupported", { message: prefixed })
                : t("python_function.rewrite_failed", { message: prefixed }),
            );
            rollbackDrafts();
            return;
          }
          // 順序が重要 (ADR-0074 V14): cache 投入 → params 更新。
          // 逆にすると canPruneOnParamChange が偽になり結線剪定がスキップされる。
          const rename = opts?.renameParam;
          let override: Record<string, unknown> | undefined;
          if (rename !== undefined) {
            const up = _userParams(block);
            if (rename.from in up) {
              const { [rename.from]: moved, ...rest } = up;
              override = { ...rest, [rename.to]: moved };
            }
          }
          const retype = opts?.retypeParam;
          if (retype !== undefined) {
            const up = override ?? _userParams(block);
            if (retype.name in up) {
              const converted = _convertUserParamValue(
                up[retype.name],
                retype.type,
                retype.from,
              );
              const { [retype.name]: _dropped, ...rest } = up;
              override =
                converted === undefined ? rest : { ...rest, [retype.name]: converted };
            }
          }
          putPythonSpec(resp.code, resp.spec);
          finishApply(resp.code, resp.spec, override);
          opts?.onApplied?.();
        })
        .catch((e: unknown) => {
          if (seq !== rewriteSeq.current) return;
          setStructError(
            t("python_function.rewrite_network_error", {
              message: e instanceof Error ? e.message : String(e),
            }),
          );
          rollbackDrafts();
        })
        .finally(() => {
          if (seq === rewriteSeq.current) setRewriteBusy(false);
        });
    },
    [block, finishApply, liveCode, rewriteBusy, rollbackDrafts, t],
  );

  const commitCount = useCallback(
    (role: "inputs" | "outputs", value: number | undefined): void => {
      if (spec === null || editable === undefined || value === undefined) return;
      const current = role === "inputs" ? spec.n_inputs : spec.n_outputs;
      const min = role === "inputs" ? editable.min_inputs : editable.min_outputs;
      const max = role === "inputs" ? editable.max_inputs : editable.max_outputs;
      // SPEC-0024 エッジケース: 小数は commit せず値を戻す (黙って丸めない)
      if (!Number.isInteger(value)) {
        setStructError(t("python_function.port_range", { max }));
        if (role === "inputs") setDraftInputs(spec.n_inputs);
        else setDraftOutputs(spec.n_outputs);
        return;
      }
      const target = value;
      if (target === current) return;
      if (target < Math.max(1, min) || target > max) {
        setStructError(t("python_function.port_range", { max }));
        // 範囲外は draft を現状に戻す
        if (role === "inputs") setDraftInputs(spec.n_inputs);
        else setDraftOutputs(spec.n_outputs);
        return;
      }
      commitRewrite({ [role]: target });
    },
    [commitRewrite, editable, spec, t],
  );

  const commitNames = useCallback(
    (role: "input_names" | "output_names", names: string[]): void => {
      if (spec === null) return;
      const current = role === "input_names" ? spec.input_names : spec.output_names;
      const padded = _paddedNames(
        current,
        role === "input_names" ? spec.n_inputs : spec.n_outputs,
      );
      if (names.every((n, i) => n === padded[i])) return;
      commitRewrite({ [role]: names });
    },
    [commitRewrite, spec],
  );

  // --- SPEC-0025: パラメータ構造編集 (追加 / 削除 / rename) ---

  const commitParamRename = useCallback(
    (from: string): void => {
      if (spec === null) return;
      const to = (draftParamNames[from] ?? from).trim();
      if (to === from) return;
      if (!_validParamName(to)) {
        setStructError(t("python_function.params.invalid_identifier"));
        setDraftParamNames((d) => ({ ...d, [from]: from }));
        return;
      }
      if (spec.params_spec.some((p) => p.name === to)) {
        setStructError(t("python_function.params.name_conflict", { name: to }));
        setDraftParamNames((d) => ({ ...d, [from]: from }));
        return;
      }
      commitRewrite(
        { params: [{ op: "rename", from, to }] },
        { renameParam: { from, to } },
      );
    },
    [commitRewrite, draftParamNames, spec, t],
  );

  const commitParamRemove = useCallback(
    (name: string): void => {
      commitRewrite({ params: [{ op: "remove", name }] });
    },
    [commitRewrite],
  );

  const commitParamRetype = useCallback(
    (name: string, type: ParamTypeName, from: string | null): void => {
      commitRewrite(
        { params: [{ op: "retype", name, type }] },
        { retypeParam: { name, type, from } },
      );
    },
    [commitRewrite],
  );

  const paramLimitReached = spec !== null && spec.params_spec.length >= MAX_PARAMS;
  const addNameTrimmed = addName.trim();
  const addDefaultValid =
    addType === "bool" || addType === "str" || parseNumericInput(addDefault) !== null;
  const canAddParam =
    !rewriteBusy &&
    spec !== null &&
    _validParamName(addNameTrimmed) &&
    !spec.params_spec.some((p) => p.name === addNameTrimmed) &&
    !paramLimitReached &&
    addDefaultValid;

  const commitParamAdd = useCallback((): void => {
    const name = addName.trim();
    let def: number | boolean | string;
    if (addType === "bool") def = addDefault === "true";
    else if (addType === "str") def = addDefault;
    else {
      const parsed = parseNumericInput(addDefault);
      if (parsed === null) return;
      def = addType === "int" ? Math.trunc(parsed) : parsed;
    }
    commitRewrite(
      { params: [{ op: "add", name, type: addType, default: def }] },
      {
        onApplied: () => {
          setAddName("");
          setAddDefault(addType === "bool" ? "false" : addType === "str" ? "" : "0");
        },
      },
    );
  }, [addDefault, addName, addType, commitRewrite]);

  const userParams = _userParams(block);

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

  const commitOnEnter = (commit: () => void) => (e: React.KeyboardEvent<HTMLInputElement>) => {
    // IME composition 中の Enter は確定操作なので commit しない (SPEC-0022 踏襲)
    if (e.key === "Enter" && !e.nativeEvent.isComposing && !composingRef.current) {
      commit();
    }
  };

  const renderNameRows = (
    role: "input_names" | "output_names",
    drafts: string[],
    setDrafts: (v: string[]) => void,
  ): JSX.Element[] =>
    drafts.map((name, i) => {
      const label =
        role === "input_names"
          ? t("python_function.port_names.in", { index: i })
          : t("python_function.port_names.out", { index: i });
      return (
      <PropertyRow
        key={`${role}-${i}`}
        labelWidth={LABEL_W}
        labelAlign="left"
        label={label}
      >
        <TextInput
          value={name}
          disabled={rewriteBusy}
          testId={`pf-${role === "input_names" ? "in" : "out"}-name-${i}`}
          ariaLabel={label}
          widthClass="min-w-0 flex-1 max-w-[160px]"
          onChange={(v) => {
            // 32 は **コードポイント** 基準 (サーバと同じ)。HTML maxLength は
            // UTF-16 単位で絵文字が 2 消費になるため使わず、ここで切り詰める
            const cps = Array.from(v);
            const next = drafts.slice();
            next[i] = cps.length > 32 ? cps.slice(0, 32).join("") : v;
            setDrafts(next);
          }}
          onBlur={() => commitNames(role, drafts)}
          onKeyDown={commitOnEnter(() => commitNames(role, drafts))}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
        />
      </PropertyRow>
      );
    });

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
                <NumberInput
                  value={draftInputs}
                  onChange={setDraftInputs}
                  onBlur={() => commitCount("inputs", draftInputs)}
                  onKeyDown={commitOnEnter(() => commitCount("inputs", draftInputs))}
                  disabled={rewriteBusy || editable === undefined || !editable.inputs}
                  testId="pf-n-inputs-input"
                  widthClass="w-16"
                />
                <span className="sr-only" data-testid="pf-n-inputs">{spec.n_inputs}</span>
              </PropertyRow>
              {editable !== undefined && !editable.inputs && (
                <PropertyHint
                  labelWidth={LABEL_W}
                  testId="pf-inputs-locked-hint"
                  text={t("python_function.inputs_locked_no_u")}
                />
              )}
              <PropertyRow labelWidth={LABEL_W} labelAlign="left" label={t("python_function.outputs")}>
                <NumberInput
                  value={draftOutputs}
                  onChange={setDraftOutputs}
                  onBlur={() => commitCount("outputs", draftOutputs)}
                  onKeyDown={commitOnEnter(() => commitCount("outputs", draftOutputs))}
                  disabled={rewriteBusy}
                  testId="pf-n-outputs-input"
                  widthClass="w-16"
                />
                <span className="sr-only" data-testid="pf-n-outputs">{spec.n_outputs}</span>
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
          {structError !== null && (
            <div
              role="alert"
              data-testid="pf-struct-error"
              className="border border-rose-300 bg-rose-50 px-2 py-1 font-mono text-[10px] text-rose-700 whitespace-pre-wrap"
            >
              {structError}
            </div>
          )}

          {spec !== null && (
            <>
              <SectionDivider label={t("python_function.section.port_names")} />
              {renderNameRows("input_names", draftInNames, setDraftInNames)}
              {renderNameRows("output_names", draftOutNames, setDraftOutNames)}
            </>
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
              const isX0 = spec.n_states > 0 && p.name === "x0";
              const nameDraft = draftParamNames[p.name] ?? p.name;
              const valueControl =
                p.type === "bool" ? (
                  <select
                    data-testid={testId}
                    value={current === true ? "true" : "false"}
                    onChange={(e) => commitUserParam(p, e.target.value)}
                    className={`${SELECT_CLS} min-w-0 w-24`}
                  >
                    <option value="false">false</option>
                    <option value="true">true</option>
                  </select>
                ) : (
                  <UserParamInput
                    spec={p}
                    value={current}
                    testId={testId}
                    placeholder={!p.has_default ? t("python_function.required") : ""}
                    onCommit={(raw) => commitUserParam(p, raw)}
                  />
                );
              return (
                <Fragment key={p.name}>
                  <PropertyRow
                    labelWidth={LABEL_W}
                    labelAlign="left"
                    label={p.name}
                    labelControl={
                      <TextInput
                        value={nameDraft}
                        mono
                        maxLength={64}
                        disabled={rewriteBusy || isX0}
                        testId={`pf-param-name-${p.name}`}
                        ariaLabel={t("python_function.params.name")}
                        widthClass="min-w-0 w-full"
                        onChange={(v) =>
                          setDraftParamNames((d) => ({ ...d, [p.name]: v }))
                        }
                        onBlur={() => commitParamRename(p.name)}
                        onKeyDown={commitOnEnter(() => commitParamRename(p.name))}
                        onCompositionStart={() => {
                          composingRef.current = true;
                        }}
                        onCompositionEnd={() => {
                          composingRef.current = false;
                        }}
                      />
                    }
                    action={
                      <RowActionButton
                        tone="danger"
                        icon="remove"
                        disabled={rewriteBusy || isX0}
                        onClick={() => commitParamRemove(p.name)}
                        testId={`pf-param-remove-${p.name}`}
                        ariaLabel={t("python_function.params.remove")}
                      />
                    }
                  >
                    {(PARAM_TYPE_OPTIONS as readonly string[]).includes(p.type ?? "") &&
                    !isX0 ? (
                      <select
                        data-testid={`pf-param-type-${p.name}`}
                        aria-label={t("python_function.params.type")}
                        value={p.type ?? ""}
                        disabled={rewriteBusy}
                        onChange={(e) =>
                          commitParamRetype(
                            p.name,
                            e.target.value as ParamTypeName,
                            p.type ?? null,
                          )
                        }
                        className={`${SELECT_CLS} mr-1 w-16 shrink-0`}
                      >
                        {PARAM_TYPE_OPTIONS.map((tn) => (
                          <option key={tn} value={tn}>
                            {tn}
                          </option>
                        ))}
                      </select>
                    ) : (
                      // 語彙外の型 (np.float64 等) / x0 は read-only 表示 (見える化のみ)
                      <span
                        data-testid={`pf-param-type-${p.name}`}
                        title={p.type ?? ""}
                        className="mr-1 w-16 shrink-0 truncate text-[10px] text-slate-500"
                      >
                        {p.type ?? "?"}
                      </span>
                    )}
                    {valueControl}
                  </PropertyRow>
                  {isX0 && (
                    <PropertyHint
                      labelWidth={LABEL_W}
                      testId="pf-param-x0-hint"
                      text={t("python_function.params.reserved_x0")}
                    />
                  )}
                </Fragment>
              );
            })}
          {spec !== null && (
            <>
              <SectionDivider label={t("python_function.params.new")} />
              <PropertyRow
                labelWidth={LABEL_W}
                labelAlign="left"
                label={t("python_function.params.name")}
                labelControl={
                  <TextInput
                    value={addName}
                    mono
                    maxLength={64}
                    disabled={rewriteBusy}
                    placeholder={t("python_function.params.name")}
                    testId="pf-param-add-name"
                    ariaLabel={t("python_function.params.name")}
                    widthClass="min-w-0 w-full"
                    onChange={setAddName}
                    onKeyDown={commitOnEnter(() => {
                      if (canAddParam) commitParamAdd();
                    })}
                    onCompositionStart={() => {
                      composingRef.current = true;
                    }}
                    onCompositionEnd={() => {
                      composingRef.current = false;
                    }}
                  />
                }
                action={
                  <RowActionButton
                    icon="add"
                    disabled={!canAddParam}
                    onClick={commitParamAdd}
                    testId="pf-param-add-submit"
                    ariaLabel={t("python_function.params.add")}
                  />
                }
              >
                <select
                  data-testid="pf-param-add-type"
                  aria-label={t("python_function.params.type")}
                  value={addType}
                  disabled={rewriteBusy}
                  onChange={(e) => {
                    const next = e.target.value as "float" | "int" | "bool" | "str";
                    setAddType(next);
                    setAddDefault(next === "bool" ? "false" : next === "str" ? "" : "0");
                  }}
                  className={`${SELECT_CLS} w-16 shrink-0`}
                >
                  <option value="float">float</option>
                  <option value="int">int</option>
                  <option value="bool">bool</option>
                  <option value="str">str</option>
                </select>
                {addType === "bool" ? (
                  <select
                    data-testid="pf-param-add-default"
                    aria-label={t("python_function.params.default")}
                    value={addDefault}
                    disabled={rewriteBusy}
                    onChange={(e) => setAddDefault(e.target.value)}
                    className={`${SELECT_CLS} ml-1 w-16 shrink-0`}
                  >
                    <option value="false">false</option>
                    <option value="true">true</option>
                  </select>
                ) : (
                  <input
                    type="text"
                    inputMode={addType === "str" ? undefined : "decimal"}
                    data-testid="pf-param-add-default"
                    aria-label={t("python_function.params.default")}
                    value={addDefault}
                    disabled={rewriteBusy}
                    onChange={(e) => setAddDefault(e.target.value)}
                    className={`${INPUT_MONO_CLS} ml-1 min-w-0 flex-1 max-w-[90px]`}
                  />
                )}
              </PropertyRow>
              {paramLimitReached && (
                <PropertyHint
                  labelWidth={LABEL_W}
                  testId="pf-param-limit-hint"
                  text={t("python_function.params.limit_reached")}
                />
              )}
            </>
          )}
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
