// ADR-0080 §A5: libraries query (ライブラリ一覧) の共有定義。
//
// 書き込みに成功したタブは ``LIBRARIES_QUERY_KEY`` を invalidate する。他タブには push
// しない代わりに ``staleTime: 0`` + ``refetchOnWindowFocus: true`` で、タブに戻った
// とき (focus) に取り直す。一覧は metadata のみで軽い。取りこぼしがあっても、書き込み
// 側の 409 (``expected_revision`` / ディスク変更検知) で正しさは保たれる。

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useMemo } from "react";

import { listLibraries } from "../api/client";
import type { LibraryRegistryResponse } from "../types/api";
import { buildLibraryIndex, type LibraryIndex } from "./libraryProvenance";

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

/** ``useLibraryIndex`` の結果。 */
export interface LibraryIndexState {
  index: LibraryIndex;
  /** 一覧を取得済みか。false の間は「由来先が見つからない」と断定してはいけない。 */
  ready: boolean;
  /** 一覧を 1 度も取得できず、取得に失敗しているか。 */
  failed: boolean;
}

/**
 * 由来の解決用の索引。ライブラリ一覧が取り直されたとき (書き込み成功・タブへの
 * focus 復帰) だけ作り直すので、更新マーカーや Inspector の由来表示が一覧に追従する。
 */
export function useLibraryIndex(): LibraryIndexState {
  const { data, isError } = useLibrariesQuery();
  const index = useMemo(() => buildLibraryIndex(data?.libraries ?? []), [data]);
  return { index, ready: data !== undefined, failed: data === undefined && isError };
}
