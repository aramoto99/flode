// Block の type_path 定数を集約。`appStore.ts` の auto-resize ロジックと
// テストの両方から import されることで、片方の文字列を変更し忘れて整合が
// 崩れるリスクを排除する (= code-reviewer NITS-2)。

export const SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem";
export const INPORT_TYPE = "flode.subsystems.ports.Inport";
export const OUTPORT_TYPE = "flode.subsystems.ports.Outport";

// ADR-0058: Subsystem behavior modifier control blocks。Subsystem 内部に置く
// ことで親の発火 / 有効化セマンティクスを修飾する境界ブロック。Inport /
// Outport と並ぶ「control」カテゴリ。
export const TRIGGER_TYPE = "flode.subsystems.control_blocks.Trigger";
export const ENABLE_TYPE = "flode.subsystems.control_blocks.Enable";

// SPEC-0023 / ADR-0073: ユーザー Python (@block 形) を実行するブロック。ポート数は
// ``params.code`` の静的解析 (introspect API) で決まる (= lib/pythonFunctionSpec.ts)。
export const PYTHON_FUNCTION_TYPE = "flode.blocks.pythonfunc.PythonFunction";

/**
 * `params[key]` を number として取り出す。値が number でなければ `fallback` を返す。
 * `as number` の二段キャストが NaN を黙って混入させる罠を避けるための型ガード
 * (= code-reviewer SHOULD-1)。
 */
export function getNumberParam(
  params: Record<string, unknown>,
  key: string,
  fallback = 0,
): number {
  const v = params[key];
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
