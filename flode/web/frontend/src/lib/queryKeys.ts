// react-query の queryKey の共有定数。

/**
 * block registry (``GET /api/v1/blocks``) の queryKey。パレット・QuickAdd・コマンド
 * パレット・キャンバス・Inspector・ショートカットが共有し、ユーザーブロックの再読み込み
 * (ADR-0081 §8-C) はこの key を更新・invalidate する。
 */
export const BLOCKS_REGISTRY_QUERY_KEY = ["blocks-registry"] as const;
