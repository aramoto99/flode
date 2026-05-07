// ADR-0021 §(3): Subsystem ドリルダウン階層の breadcrumb。
// `Top › sub_outer › sub_inner` のクリック可能パスを表示し、
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
      className="flex items-center gap-1.5 border-b border-slate-200 bg-white px-3 py-1.5 text-xs"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5 text-slate-400"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 12l9-9 9 9M5 10v10h14V10" />
      </svg>
      <button
        type="button"
        onClick={goTop}
        className={
          editingPath.length === 0
            ? "font-medium text-slate-700"
            : "text-blue-600 transition-colors hover:text-blue-800 hover:underline"
        }
      >
        Top
      </button>
      {editingPath.map((segId, idx) => {
        const isLast = idx === editingPath.length - 1;
        return (
          <span key={`${idx}-${segId}`} className="flex items-center gap-1.5">
            <span className="text-slate-300">›</span>
            <button
              type="button"
              onClick={() => goAt(idx)}
              className={
                isLast
                  ? "font-medium text-slate-700"
                  : "text-blue-600 transition-colors hover:text-blue-800 hover:underline"
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
