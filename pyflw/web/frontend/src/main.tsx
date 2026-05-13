import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import "./i18n"; // ADR-0024: i18next を起動時に同期 init (FOUC 回避)
import "./index.css";
// v0.31.2: QueryClient を別 module に切り出し、commands.ts 等から
// invalidateQueries を呼べるようにする。
import { queryClient } from "./lib/queryClient";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root container not found in index.html");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
