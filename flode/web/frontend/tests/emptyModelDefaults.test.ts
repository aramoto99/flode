// bug-fix 2026-09-13: 新規モデルの solver 既定値はエンジン Simulator.__init__ の既定
// (RK45 / dt=0.01 / rtol=1e-6 / atol=1e-9) と一致していなければならない。従来は
// scipy 既定 (1e-3 / 1e-6) が入っており、GUI で作ったモデルだけ 1000 倍緩かった。
import { describe, expect, it } from "vitest";

import { CURRENT_SCHEMA_VERSION, emptyModel } from "../src/lib/emptyModel";

describe("emptyModel の solver 既定値", () => {
  it("エンジン Simulator の既定 (RK45 / 0.01 / 1e-6 / 1e-9) と一致する", () => {
    const m = emptyModel("demo");
    expect(m.simulator).toEqual({
      t_end: 10.0,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    });
    expect(m.schema_version).toBe(CURRENT_SCHEMA_VERSION);
    expect(m.blocks).toEqual([]);
    expect(m.connections).toEqual([]);
  });
});
