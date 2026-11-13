// ADR-0081 §2-A / §8-C: ユーザーブロックの「再読み込み」操作。
//
// 成功したら block registry query (``["blocks-registry"]``、パレット・QuickAdd・コマンド
// パレット・キャンバス・Inspector が共有) を invalidate し、結果をトーストで知らせる。
// 失敗 (403 / 400 / 409 / 500 / 通信エラー) はエラーのトースト。要求中はもう一度
// 実行しない (サーバ側も 409 で拒否するが、二重送信自体を作らない)。

import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, reloadBlocks } from "../api/client";
import { pushToast } from "../store/toastStore";
import type { BlockRegistryResponse, BlockReloadResponse } from "../types/api";
import { BLOCKS_REGISTRY_QUERY_KEY } from "./queryKeys";
import { cleanServerText, MAX_LABEL_CHARS, MAX_MESSAGE_CHARS } from "./untrustedText";

/** サーバが返す ``error.user_blocks.<code>`` のうち文言を持つもの。 */
const KNOWN_RELOAD_ERROR_CODES = new Set([
  "user_blocks_disabled",
  "reload_not_allowed",
  "invalid_reload_body",
  "reload_in_progress",
]);
const RELOAD_ERROR_KEY_PREFIX = "error.user_blocks.";
/** 再起動が必要な読み込み元をトーストに並べる上限 (超えた分は省略)。 */
const MAX_RESTART_SOURCES_SHOWN = 3;
const MODULE_SOURCE_PREFIX = "module:";

/**
 * 再読み込みの成功結果をトーストの文言にする。
 *
 * @param t - i18next の ``t``。
 * @param resp - ``POST /blocks/reload`` の応答。
 * @returns 文言と重要度 (読み込みエラーがあれば ``warning``)。
 */
export function formatReloadResult(
  t: TFunction,
  resp: BlockReloadResponse,
): { message: string; severity: "success" | "warning" } {
  // 応答の形が欠けていても (成功しているのに) エラーのトーストにしない
  const list = <T,>(v: T[] | undefined | null): T[] => (Array.isArray(v) ? v : []);
  const errorCount = list(resp.errors).filter((e) => e?.severity !== "info").length;
  const parts = [
    t("palette.reload.done", {
      added: list(resp.added).length,
      removed: list(resp.removed).length,
      changed: list(resp.changed).length,
    }),
  ];
  if (errorCount > 0) {
    parts.push(t("palette.reload.errors", { count: errorCount }));
  }
  const restart = list(resp.restart_required_sources).filter(
    (id): id is string => typeof id === "string",
  );
  if (restart.length > 0) {
    const names = restart
      .slice(0, MAX_RESTART_SOURCES_SHOWN)
      .map((id) =>
        cleanServerText(
          id.startsWith(MODULE_SOURCE_PREFIX) ? id.slice(MODULE_SOURCE_PREFIX.length) : id,
          MAX_LABEL_CHARS,
        ),
      );
    if (restart.length > MAX_RESTART_SOURCES_SHOWN) names.push("…");
    parts.push(t("palette.reload.restart_required", { sources: names.join(", ") }));
  }
  return {
    message: parts.join(" "),
    severity: errorCount > 0 ? "warning" : "success",
  };
}

/**
 * 再読み込みの失敗をトーストの文言にする。
 *
 * サーバの構造化エラー (``error.user_blocks.<code>``) は対応する i18n 文言、それ以外
 * (500・通信エラー・未知の code) は汎用の文言に整形済みのメッセージを添える。
 *
 * @param t - i18next の ``t``。
 * @param error - ``reloadBlocks()`` が投げた値。
 * @returns 表示する文言。
 */
export function formatReloadError(t: TFunction, error: unknown): string {
  if (error instanceof ApiError && error.structured !== null) {
    const key = error.structured.template_key;
    const code = key.startsWith(RELOAD_ERROR_KEY_PREFIX)
      ? key.slice(RELOAD_ERROR_KEY_PREFIX.length)
      : "";
    if (KNOWN_RELOAD_ERROR_CODES.has(code)) {
      return t(`${RELOAD_ERROR_KEY_PREFIX}${code}` as "error.user_blocks.reload_in_progress", {
        message: cleanServerText(error.structured.template_args.message, MAX_MESSAGE_CHARS),
      });
    }
  }
  const raw = error instanceof Error ? error.message : String(error);
  return t("palette.reload.failed", {
    message: cleanServerText(raw, MAX_MESSAGE_CHARS),
  });
}

/**
 * ユーザーブロックの再読み込みを実行する hook。
 *
 * @returns ``reload`` (要求中は何もしない) と ``pending`` (要求中か、ボタンの無効化用)。
 */
export function useBlockReload(): { reload: () => Promise<void>; pending: boolean } {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  // state は再 render まで反映されないので、同じイベント内の連打は ref で止める
  const inFlight = useRef(false);

  const reload = useCallback(async (): Promise<void> => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      const resp = await reloadBlocks();
      // 応答は GET /blocks と同じ形なので先に cache へ入れ (画面がすぐ新しい registry を
      // 見る)、invalidate で正規の再取得もさせる。トーストは再取得を待たずに出す。
      if (Array.isArray(resp.blocks)) {
        queryClient.setQueryData<BlockRegistryResponse>(BLOCKS_REGISTRY_QUERY_KEY, resp);
      }
      pushToast(formatReloadResult(t, resp));
      void queryClient.invalidateQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
    } catch (e) {
      pushToast({ severity: "error", message: formatReloadError(t, e) });
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [queryClient, t]);

  return { reload, pending };
}
