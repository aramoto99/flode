// ADR-0080 §A5: libraries query (ライブラリ一覧) の共有定義。
//
// 書き込みに成功したタブは ``LIBRARIES_QUERY_KEY`` を invalidate する。他タブには push
// しない代わりに ``staleTime: 0`` + ``refetchOnWindowFocus: true`` で、タブに戻った
// とき (focus) に取り直す。一覧は metadata のみで軽い。取りこぼしがあっても、書き込み
// 側の 409 (``expected_revision`` / ディスク変更検知) で正しさは保たれる。

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { listLibraries } from "../api/client";
import type { LibraryRegistryResponse } from "../types/api";

/** libraries query の key。 */
export const LIBRARIES_QUERY_KEY = ["libraries-registry"] as const;

/** ライブラリ一覧 (パレット表示・書き込み可否の判定) を購読する。 */
export function useLibrariesQuery(): UseQueryResult<LibraryRegistryResponse> {
  return useQuery({
    queryKey: LIBRARIES_QUERY_KEY,
    queryFn: listLibraries,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
}
