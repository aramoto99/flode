// ADR-0021 §(3): Subsystem ドリルダウン階層の breadcrumb。
// `Top > sub_outer > sub_inner` のクリック可能パスを表示し、
// 各セグメントクリックで `editingPath` を切り詰めて該当階層に戻る。

import { useAppStore } from "../store/appStore";

export function Breadcrumb(): JSX.Element {
  const editingPath = useAppStore((s) => s.editingPath);
  const drillUp = useAppStore((s) => s.drillUp);

  // depth = 0 は top-level (= 全 path クリア)、idx+1 は「idx 番目までを残す」 = depth=idx+1
  const goTop = (): void => drillUp(0);
  const goAt = (idx: number): void => drillUp(idx + 1);

  return (
    <nav
      aria-label="Subsystem path"
      className="flex items-center gap-1 border-b border-gray-200 bg-gray-50 px-3 py-1 text-xs"
    >
      <button
        type="button"
        onClick={goTop}
        className={
          editingPath.length === 0
            ? "font-medium text-gray-700"
            : "text-blue-600 hover:underline"
        }
      >
        Top
      </button>
      {editingPath.map((segId, idx) => {
        const isLast = idx === editingPath.length - 1;
        return (
          <span key={`${idx}-${segId}`} className="flex items-center gap-1">
            <span className="text-gray-400">/</span>
            <button
              type="button"
              onClick={() => goAt(idx)}
              className={
                isLast
                  ? "font-medium text-gray-700"
                  : "text-blue-600 hover:underline"
              }
              disabled={isLast}
              title={isLast ? "current scope" : `go to ${segId}`}
            >
              {segId}
            </button>
          </span>
        );
      })}
    </nav>
  );
}
