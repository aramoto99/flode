// Block の type_path 定数を集約。`appStore.ts` の auto-resize ロジックと
// テストの両方から import されることで、片方の文字列を変更し忘れて整合が
// 崩れるリスクを排除する (= code-reviewer NITS-2)。

export const SUBSYSTEM_TYPE = "pyflw.subsystems.subsystem.Subsystem";
export const TRIGGERED_SUBSYSTEM_TYPE =
  "pyflw.subsystems.triggered.TriggeredSubsystem";
export const INPORT_TYPE = "pyflw.subsystems.ports.Inport";
export const OUTPORT_TYPE = "pyflw.subsystems.ports.Outport";

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
