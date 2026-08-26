// SPEC-0023 / ADR-0073: PythonFunction spec cache の世代を購読する React hook。
// introspect が完了すると世代が進み、購読中のコンポーネント (DiagramCanvas /
// PythonFunctionEditor) が再描画されてポート数・構造表示が確定値に置き換わる。

import { useSyncExternalStore } from "react";

import { getPythonSpecVersion, subscribePythonSpecs } from "./pythonFunctionSpec";

export function usePythonSpecVersion(): number {
  return useSyncExternalStore(
    subscribePythonSpecs,
    getPythonSpecVersion,
    getPythonSpecVersion,
  );
}
