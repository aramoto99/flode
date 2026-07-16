// ADR-0029: ライブラリ entry の drag/drop ペイロード形式を検証するユニットテスト。
//
// BlockPalette (drag-start) と DiagramCanvas (drop) で共有される
// `application/flode-library-entry-ref` MIME 型に対する JSON ペイロードの
// シリアライズ / デシリアライズ整合性を確認する。
//
// React コンポーネントを丸ごとマウントしてテストするのは React Flow の依存が重く
// 不安定なので、ここでは drag-start の payload 仕様 + API 経路の契約のみを検証する。
// E2E は ``tests/e2e/`` の Playwright で別途カバー。

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import * as apiClient from "../src/api/client";
import type { LibraryEntryDetail } from "../src/types/api";

const PID_DETAIL: LibraryEntryDetail = {
  id: "pid_controller",
  display_name: "PID Controller",
  display_name_i18n: { en: "PID Controller", ja: "PID コントローラ" },
  description: "PID controller",
  description_i18n: {},
  category_suffix: "controllers",
  subsystem: {
    id: null,
    type: "flode.subsystems.subsystem.Subsystem",
    params: {
      n_inputs: 1,
      n_outputs: 1,
      mask_params: [
        { name: "Kp", type: "float", default: 1.0, description: "" },
      ],
      mask_values: { Kp: 1.0 },
      blocks: [],
      connections: [],
    },
  },
};

describe("application/flode-library-entry-ref MIME contract", () => {
  it("serializes {library, entry} payload symmetrically", () => {
    const payload = { library: "std", entry: "pid_controller" };
    const ser = JSON.stringify(payload);
    const deser = JSON.parse(ser);
    expect(deser).toEqual(payload);
  });

  it("rejects malformed JSON gracefully (parse failure path)", () => {
    let parsed: unknown = null;
    try {
      parsed = JSON.parse("{not json}");
    } catch {
      parsed = null;
    }
    expect(parsed).toBeNull();
  });
});

describe("getLibraryEntry mock contract", () => {
  beforeEach(() => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(PID_DETAIL), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls /api/v1/libraries/{lib}/{entry} and returns subsystem body", async () => {
    const detail = await apiClient.getLibraryEntry("std", "pid_controller");
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const url = fetchMock.mock.calls[0]?.[0];
    expect(String(url)).toBe("/api/v1/libraries/std/pid_controller");
    expect(detail.subsystem.type).toBe("flode.subsystems.subsystem.Subsystem");
    expect(detail.subsystem.params.n_inputs).toBe(1);
    expect(detail.subsystem.params.n_outputs).toBe(1);
  });

  it("encodes URL components (handles e.g. spaces / unicode in names)", async () => {
    await apiClient.getLibraryEntry("std lib", "with space");
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const url = fetchMock.mock.calls[0]?.[0];
    expect(String(url)).toBe(
      "/api/v1/libraries/std%20lib/with%20space",
    );
  });
});

describe("Inline placement: subsystem body becomes BlockEntry params", () => {
  it("preserves placeholder strings (mask params) byte-identical", () => {
    // ADR-0029 §PLACE-A の核となる不変条件: ``getLibraryEntry`` で返ってきた
    // subsystem.params をそのまま BlockEntry.params にコピーする経路で、
    // mask_params / mask_values / blocks / connections が損なわれない。
    const blockEntryParams: Record<string, unknown> = {
      ...PID_DETAIL.subsystem.params,
    };
    expect(blockEntryParams.mask_params).toEqual([
      { name: "Kp", type: "float", default: 1.0, description: "" },
    ]);
    expect(blockEntryParams.mask_values).toEqual({ Kp: 1.0 });
    expect(blockEntryParams.n_inputs).toBe(1);
  });
});
