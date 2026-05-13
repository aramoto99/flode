// v0.31.2: QueryClient を module-export し、React component 外 (= commands.ts /
// 各種 helper) からも `invalidateQueries` を呼べるようにする。
//
// 旧 v0.31.1 まで: ``main.tsx`` 内 local ``new QueryClient()``、外から触れない。
// 新 v0.31.2: 本 module で singleton を保持、`<QueryClientProvider>` に渡す
// 唯一のインスタンス。
//
// ADR-0019 / ADR-0028 などで使われる queryKey 規約は変えない (= 既存 cache 互換)。

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});
