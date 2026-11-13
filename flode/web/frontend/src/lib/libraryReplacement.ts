// ADR-0080 §A7 / SPEC-0032 §1.4-6: 配置済みブロックを、ライブラリの現在の版で
// 差し替えるための純関数群。
//
// - ``checkReplacementCompatibility``: 既存の接続を保てるか (A7-1)
// - ``carryOverValues``: 同名かつ型が合うパラメータ値の引き継ぎ (A7-2)
// - ``replaceBlockInModel``: モデルへの適用 (id・位置・接続は保持、A7-2 / A7-3)
//
// 通信・確認・適用直前の再確認は ``lib/libraryReplacementFlow.ts`` が持つ。

import type {
  BlockEntry,
  BlockProvenance,
  ConnectionEntry,
  FlwModel,
  PythonFunctionIntrospectResult,
} from "../types/api";
import { INPORT_TYPE, OUTPORT_TYPE, PYTHON_FUNCTION_TYPE, SUBSYSTEM_TYPE } from "./blockTypes";
import {
  countSubsystemOutputs,
  resolveSubsystemInputSlots,
  type InputSlotKind,
} from "./dynamicPorts";
import {
  applyAtPath,
  applyBranchWaypointsAtPath,
  resolveBlocksAtPath,
} from "./pathResolver";

/** PythonFunction のコードから静的解析結果を引く関数 (未取得なら ``undefined``)。 */
export type SpecLookup = (code: unknown) => PythonFunctionIntrospectResult | undefined;

/** ブロック本体 (ライブラリエントリの ``block`` / 配置済みブロック) の最小形。 */
export interface BlockBody {
  type: string;
  params: Record<string, unknown>;
}

/** 差し替えを拒否する理由 1 件。 */
export type ReplacementIssue =
  /** PythonFunction のポート構成を確定できない (静的解析が未取得・失敗)。 */
  | { kind: "spec_unavailable"; side: "old" | "new" }
  /** ポート構成が分からない種別 (ライブラリエントリになりえない型)。 */
  | { kind: "unsupported_type"; side: "old" | "new"; type: string }
  /** 接続中の入力 index が新版に無い。 */
  | { kind: "input_missing"; index: number }
  /** 接続中の入力 index のスロット種別 (data / enable / trigger) が変わる。 */
  | { kind: "input_kind_changed"; index: number; from: InputSlotKind; to: InputSlotKind }
  /** 接続中の出力 index が新版に無い。 */
  | { kind: "output_missing"; index: number };

/** 互換判定の結果。 */
export type ReplacementCompatibility =
  | {
      ok: true;
      /** 新版の出力ポート数 (``branch_waypoints`` の整理に使う)。 */
      nOutputs: number;
      /** 名前が変わった・無くなったポート (拒否理由ではなく、差し替え後に通知する)。 */
      portNameChanges: string[];
    }
  | { ok: false; issues: ReplacementIssue[] };

/** ブロック外面のポート構成。 */
interface PortLayout {
  inputs: InputSlotKind[];
  nOutputs: number;
  inputNames: string[];
  outputNames: string[];
}

/** Subsystem 内部の境界ブロック (Inport / Outport) の id を ``port_idx`` 順に返す。 */
function boundaryNames(innerBlocks: unknown[], typePath: string): string[] {
  return innerBlocks
    .filter(
      (b): b is BlockEntry =>
        typeof b === "object" && b !== null && (b as BlockEntry).type === typePath,
    )
    .map((b, order) => {
      const idx = b.params?.port_idx;
      return { id: String(b.id), idx: typeof idx === "number" ? idx : order };
    })
    .sort((a, b) => a.idx - b.idx)
    .map((b) => b.id);
}

/** ブロック本体から外面のポート構成を求める。確定できなければ理由を返す。 */
function describePorts(
  body: BlockBody,
  side: "old" | "new",
  getSpec: SpecLookup,
): PortLayout | ReplacementIssue {
  if (body.type === SUBSYSTEM_TYPE) {
    const inner = Array.isArray(body.params.blocks) ? (body.params.blocks as unknown[]) : [];
    return {
      inputs: resolveSubsystemInputSlots(inner),
      nOutputs: countSubsystemOutputs(inner),
      inputNames: boundaryNames(inner, INPORT_TYPE),
      outputNames: boundaryNames(inner, OUTPORT_TYPE),
    };
  }
  if (body.type === PYTHON_FUNCTION_TYPE) {
    // 未取得のとき registry 既定 (1 in / 1 out) で判定しない (ADR-0080 §A7-1)
    const spec = getSpec(body.params.code);
    if (spec === undefined || !spec.resolved) return { kind: "spec_unavailable", side };
    return {
      inputs: new Array<InputSlotKind>(spec.n_inputs).fill("data"),
      nOutputs: spec.n_outputs,
      inputNames: spec.input_names,
      outputNames: spec.output_names,
    };
  }
  return { kind: "unsupported_type", side, type: body.type };
}

function isIssue(value: PortLayout | ReplacementIssue): value is ReplacementIssue {
  return "kind" in value;
}

/** 位置ごとに名前を比べ、変わった・無くなったものを ``旧 → 新`` の形で列挙する。 */
function diffNames(oldNames: string[], newNames: string[], prefix: string): string[] {
  const out: string[] = [];
  oldNames.forEach((name, i) => {
    const next = newNames[i];
    if (next === undefined) out.push(`${prefix}[${i}] ${name} → —`);
    else if (next !== name) out.push(`${prefix}[${i}] ${name} → ${next}`);
  });
  return out;
}

/**
 * 差し替えで既存の接続を保てるかを判定する (ADR-0080 §A7-1)。
 *
 * 接続されている各入力 index が新版にも存在し、その index のスロット種別
 * (data / enable / trigger) が変わらないこと。出力も接続されている index が新版に
 * 存在すること。未接続ポートの増減は許す。shape / dtype は比較しない (差し替え後の
 * 通常の形状解決に任せる)。ポート名の変化は拒否理由にせず、通知用に返す。
 *
 * @param oldBlock 配置済みのブロック。
 * @param newBody ライブラリの現在の版の本体。
 * @param connections ``oldBlock`` がある階層の接続。
 * @param getSpec PythonFunction の静的解析結果の lookup (新旧とも取得済みであること)。
 */
export function checkReplacementCompatibility(
  oldBlock: BlockEntry,
  newBody: BlockBody,
  connections: readonly ConnectionEntry[],
  getSpec: SpecLookup,
): ReplacementCompatibility {
  const oldPorts = describePorts(oldBlock, "old", getSpec);
  const newPorts = describePorts(newBody, "new", getSpec);
  const issues: ReplacementIssue[] = [];
  if (isIssue(oldPorts)) issues.push(oldPorts);
  if (isIssue(newPorts)) issues.push(newPorts);
  if (isIssue(oldPorts) || isIssue(newPorts)) return { ok: false, issues };

  const usedInputs = new Set<number>();
  const usedOutputs = new Set<number>();
  for (const c of connections) {
    if (c.dst === oldBlock.id) usedInputs.add(c.dst_idx);
    if (c.src === oldBlock.id) usedOutputs.add(c.src_idx);
  }
  for (const index of [...usedInputs].sort((a, b) => a - b)) {
    const to = newPorts.inputs[index];
    // 旧版に無い index への接続 (壊れた接続) は data 扱いで比べる
    const from = oldPorts.inputs[index] ?? "data";
    if (to === undefined) issues.push({ kind: "input_missing", index });
    else if (to !== from) issues.push({ kind: "input_kind_changed", index, from, to });
  }
  for (const index of [...usedOutputs].sort((a, b) => a - b)) {
    if (index >= newPorts.nOutputs) issues.push({ kind: "output_missing", index });
  }
  if (issues.length > 0) return { ok: false, issues };
  return {
    ok: true,
    nOutputs: newPorts.nOutputs,
    portNameChanges: [
      ...diffNames(oldPorts.inputNames, newPorts.inputNames, "in"),
      ...diffNames(oldPorts.outputNames, newPorts.outputNames, "out"),
    ],
  };
}

/** 値が宣言型に合うか (float ← int / float、int ← 整数値、bool ← bool、str ← 文字列)。 */
function fitsDeclaredType(value: unknown, declared: unknown): boolean {
  switch (declared) {
    case "float":
      return typeof value === "number" && Number.isFinite(value);
    case "int":
      return typeof value === "number" && Number.isInteger(value);
    case "bool":
      return typeof value === "boolean";
    case "str":
      return typeof value === "string";
    default:
      return false;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * 旧 ``values`` のうち、新版の宣言 (名前 → 型) にあり型が合うものを新版の既定値に
 * 重ねる。引き継げなかった旧名 (宣言から消えた・型が合わない) を ``notCarried`` に積む。
 */
function mergeDeclaredValues(
  oldValues: Record<string, unknown>,
  newDefaults: Record<string, unknown>,
  declared: ReadonlyMap<string, unknown>,
  notCarried: string[],
): Record<string, unknown> {
  const merged = { ...newDefaults };
  for (const [name, value] of Object.entries(oldValues)) {
    if (declared.has(name) && fitsDeclaredType(value, declared.get(name))) {
      merged[name] = value;
    } else {
      notCarried.push(name);
    }
  }
  return merged;
}

/** ``[{name, type}]`` 形の宣言を 名前 → 型 の Map にする (形が不正な要素は無視)。 */
function declaredTypes(specs: unknown): Map<string, unknown> {
  const out = new Map<string, unknown>();
  if (!Array.isArray(specs)) return out;
  for (const spec of specs) {
    const { name, type } = asRecord(spec);
    if (typeof name === "string") out.set(name, type);
  }
  return out;
}

/**
 * 新版の本体に、旧ブロックの値を引き継いだ ``params`` を作る (ADR-0080 §A7-2)。
 *
 * - Subsystem: 同名のマスクパラメータの値を、新版の宣言にあり型が合うときだけ。
 * - PythonFunction: ``user_params`` の同名キーを、新版のコードが宣言していて型が
 *   合うときだけ。
 * - それ以外は新版の既定値 (= エントリに保存された値)。
 *
 * @returns 新しい ``params`` と、引き継げなかった旧パラメータ名 (黙って既定値にしない
 *   ために通知する)。
 */
export function carryOverValues(
  oldBlock: BlockBody,
  newBody: BlockBody,
  getSpec: SpecLookup,
): { params: Record<string, unknown>; notCarried: string[] } {
  const notCarried: string[] = [];
  const params = { ...newBody.params };
  if (oldBlock.type === SUBSYSTEM_TYPE && newBody.type === SUBSYSTEM_TYPE) {
    const oldValues = asRecord(oldBlock.params.mask_values);
    if (Object.keys(oldValues).length > 0) {
      const merged = mergeDeclaredValues(
        oldValues,
        asRecord(newBody.params.mask_values),
        declaredTypes(newBody.params.mask_params),
        notCarried,
      );
      // 新版がマスクを持たないなら ``mask_values`` キーを新たに作らない
      if ("mask_values" in newBody.params || Object.keys(merged).length > 0) {
        params.mask_values = merged;
      }
    }
  } else if (oldBlock.type === PYTHON_FUNCTION_TYPE && newBody.type === PYTHON_FUNCTION_TYPE) {
    const oldValues = asRecord(oldBlock.params.user_params);
    if (Object.keys(oldValues).length > 0) {
      const spec = getSpec(newBody.params.code);
      const merged = mergeDeclaredValues(
        oldValues,
        asRecord(newBody.params.user_params),
        declaredTypes(spec !== undefined && spec.resolved ? spec.params_spec : []),
        notCarried,
      );
      if ("user_params" in newBody.params || Object.keys(merged).length > 0) {
        params.user_params = merged;
      }
    }
  }
  return { params, notCarried };
}

/** ブロック (入れ子を含む) の中にある全 block id を集める。 */
function collectInnerIds(params: Record<string, unknown>, into: Set<string>): void {
  if (!Array.isArray(params.blocks)) return;
  for (const b of params.blocks as BlockEntry[]) {
    if (typeof b !== "object" || b === null) continue;
    into.add(String(b.id));
    collectInnerIds(asRecord(b.params), into);
  }
}

/** top-level のブロックとその内部 (入れ子を含む) の全 block id を集める。 */
function collectModelIds(blocks: readonly BlockEntry[], into: Set<string>): void {
  for (const b of blocks) {
    into.add(b.id);
    collectInnerIds(asRecord(b.params), into);
  }
}

/**
 * ``path`` にある ``blockId`` のブロックを ``replacement`` に置き換えたモデルを返す
 * (ADR-0080 §A7-2 / §A7-3)。
 *
 * - ブロック id・layout (位置・サイズ・反転)・外部接続は変えない。
 * - ``branch_waypoints``: 置き換えたブロックの出力のうち、新版に残らない index の
 *   ものを削除する。
 * - ``scope_settings`` (top-level、Scope の block id がキー): 旧版の内部にあって
 *   新版の内部に無く、モデルの他の場所にも同じ id が無いキーを削除する。
 *
 * 対象が見つからなければ ``model`` をそのまま返す (呼び出し側の no-op 判定用)。
 *
 * @param nOutputs 新版の出力ポート数。
 */
export function replaceBlockInModel(
  model: FlwModel,
  path: readonly string[],
  blockId: string,
  replacement: BlockEntry,
  nOutputs: number,
): FlwModel {
  let oldBlock: BlockEntry | undefined;
  try {
    oldBlock = resolveBlocksAtPath(model, path).blocks.find((b) => b.id === blockId);
  } catch {
    return model;
  }
  if (oldBlock === undefined) return model;
  const target = oldBlock;

  let updated = applyAtPath(model, path, (view) => ({
    ...view,
    blocks: view.blocks.map((b) => (b === target ? replacement : b)),
  }));

  updated = applyBranchWaypointsAtPath(updated, path, (waypoints) => {
    const prefix = `${blockId}:`;
    const kept = Object.entries(waypoints).filter(([key]) => {
      const sep = key.lastIndexOf(":");
      if (key.slice(0, sep + 1) !== prefix) return true;
      const index = Number(key.slice(sep + 1));
      // 出力 index として読めないキーは対象外 (触らない)
      return !Number.isInteger(index) || index < nOutputs;
    });
    return kept.length === Object.keys(waypoints).length
      ? waypoints
      : Object.fromEntries(kept);
  });

  if (updated.scope_settings) {
    const oldInner = new Set<string>();
    collectInnerIds(target.params, oldInner);
    // 置き換え後のモデルに存在する id (新版の内部を含む)
    const stillPresent = new Set<string>();
    collectModelIds(updated.blocks, stillPresent);
    const kept = Object.entries(updated.scope_settings).filter(
      ([key]) => !oldInner.has(key) || stillPresent.has(key),
    );
    if (kept.length !== Object.keys(updated.scope_settings).length) {
      const next = { ...updated };
      if (kept.length > 0) next.scope_settings = Object.fromEntries(kept);
      else delete next.scope_settings;
      updated = next;
    }
  }
  return updated;
}

/**
 * 差し替え後のブロック entry を組み立てる: id は元のまま、型と本体は新版、値は
 * 引き継ぎ済みの ``params``、由来は新版のもの。
 */
export function buildReplacementBlock(
  oldBlock: BlockEntry,
  newBody: BlockBody,
  params: Record<string, unknown>,
  provenance: BlockProvenance,
): BlockEntry {
  return { id: oldBlock.id, type: newBody.type, params, provenance };
}
