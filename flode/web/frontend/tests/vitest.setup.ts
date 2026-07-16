// Vitest 共通 setup。jsdom が提供しないブラウザ API を polyfill する。

// ResizeObserver: jsdom 未実装。UPlotChart など useEffect で使うコンポーネントの
// マウントを通すための最小スタブ (= 何もしないが API 形だけ提供)。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
    ResizeObserverStub;
}
