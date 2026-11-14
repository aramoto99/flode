// ユーザーブロックの引数の説明を表示言語で選ぶ (description_i18n → description)。

import { describe, expect, it } from "vitest";

import { userParamDescription } from "../src/lib/userBlocks";
import type { BlockParamSpec } from "../src/types/api";

const RLO = String.fromCharCode(0x202e);

function spec(overrides: Partial<BlockParamSpec> = {}): BlockParamSpec {
  return {
    name: "k",
    type: "float",
    has_default: true,
    default: 1,
    description: "Gain",
    ...overrides,
  };
}

describe("userParamDescription", () => {
  it("prefers the UI language", () => {
    const s = spec({ description_i18n: { ja: "ゲイン", en: "Gain (en)" } });
    expect(userParamDescription(s, "ja")).toBe("ゲイン");
    expect(userParamDescription(s, "en")).toBe("Gain (en)");
  });

  it("falls back to description when the language is missing", () => {
    expect(userParamDescription(spec({ description_i18n: { ja: "ゲイン" } }), "en")).toBe(
      "Gain",
    );
    expect(userParamDescription(spec(), "ja")).toBe("Gain");
  });

  it("cleans untrusted text and handles a missing spec", () => {
    expect(userParamDescription(spec({ description_i18n: { ja: `ゲ${RLO}イン` } }), "ja")).toBe(
      "ゲイン",
    );
    expect(userParamDescription(undefined, "ja")).toBe("");
  });
});
