// 新規モデルの共通 scaffold。
//
// 従来 MenuBar (File > New) / Launcher / FileBrowser の 3 箇所に同じオブジェクト
// リテラルが重複し、schema_version が "0.8" 固定のまま取り残されたり
// (エンジンは 0.9)、rtol / atol が箇所ごとに食い違うドリフトが起きていた。
// 新規モデルの形はここ 1 箇所で定義する。

import type { FlwModel } from "../types/api";

/**
 * 新規モデル作成時の schema_version。
 * エンジン側 `flode/core/persistence.py` の `CURRENT_SCHEMA_VERSION` と
 * 同期させること (ADR-0036 / ADR-0039 / ADR-0058)。
 */
export const CURRENT_SCHEMA_VERSION = "0.13";

/**
 * 空の新規モデルを作る。solver 設定はエンジン `Simulator.__init__` の既定値
 * (RK45 / rtol=1e-6 / atol=1e-9) と揃える (bug-fix 2026-09-13: 従来は scipy 既定の
 * 1e-3 / 1e-6 が入っており、GUI で作ったモデルだけ Python API より 1000 倍緩い許容誤差に
 * なっていた)。
 *
 * @param name モデル名 (拡張子 `.flw.json` を除いたベース名)
 */
export function emptyModel(name: string): FlwModel {
  return {
    schema_version: CURRENT_SCHEMA_VERSION,
    metadata: {
      name,
      created_at: new Date().toISOString(),
      tool: "flode GUI",
    },
    simulator: {
      t_end: 10.0,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}
