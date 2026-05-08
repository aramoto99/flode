// ADR-0029: blockI18n.ts の generics 化テスト (`localizeName`, `localizeDescription`)。
// LibraryEntry / Library など `BlockMetadata` 以外のオブジェクトに同パターンを
// 適用できることを検証する。

import { describe, expect, it } from "vitest";

import { localizeDescription, localizeName } from "../src/lib/blockI18n";
import type {
  LibraryEntryMetadata,
  LibraryMetadata,
} from "../src/types/api";

const PID_ENTRY: LibraryEntryMetadata = {
  id: "pid_controller",
  display_name: "PID Controller",
  display_name_i18n: { en: "PID Controller", ja: "PID コントローラ" },
  description: "PID controller (Kp, Ki, Kd).",
  description_i18n: {
    en: "PID controller (Kp, Ki, Kd).",
    ja: "PID コントローラ (Kp / Ki / Kd)。",
  },
  category_suffix: "controllers",
};

const STD_LIBRARY: LibraryMetadata = {
  name: "std",
  display_name: "Standard Library",
  display_name_i18n: { en: "Standard Library", ja: "標準ライブラリ" },
  description: "Built-in.",
  description_i18n: { en: "Built-in.", ja: "組み込み。" },
  version: "1.0.0",
  entries: [PID_ENTRY],
};

describe("localizeName (generic)", () => {
  it("returns locale-specific name when present (entry)", () => {
    expect(localizeName(PID_ENTRY, PID_ENTRY.id, "ja")).toBe("PID コントローラ");
    expect(localizeName(PID_ENTRY, PID_ENTRY.id, "en")).toBe("PID Controller");
  });

  it("returns locale-specific name when present (library)", () => {
    expect(localizeName(STD_LIBRARY, STD_LIBRARY.name, "ja")).toBe("標準ライブラリ");
    expect(localizeName(STD_LIBRARY, STD_LIBRARY.name, "en")).toBe(
      "Standard Library",
    );
  });

  it("falls back to display_name when i18n is missing for that locale", () => {
    const partial: LibraryEntryMetadata = {
      ...PID_ENTRY,
      display_name_i18n: { en: "PID Controller" }, // ja 未登録
    };
    expect(localizeName(partial, partial.id, "ja")).toBe("PID Controller");
  });

  it("falls back to display_name when i18n missing entirely (legacy)", () => {
    const legacy: LibraryEntryMetadata = {
      ...PID_ENTRY,
      display_name_i18n: {},
    };
    expect(localizeName(legacy, legacy.id, "ja")).toBe("PID Controller");
  });

  it("falls back to fallback id when both i18n and display_name absent", () => {
    const stripped: LibraryEntryMetadata = {
      ...PID_ENTRY,
      display_name: "",
      display_name_i18n: {},
    };
    expect(localizeName(stripped, stripped.id, "ja")).toBe("pid_controller");
  });

  it("treats empty string as missing (||) in i18n value", () => {
    const empty: LibraryEntryMetadata = {
      ...PID_ENTRY,
      display_name_i18n: { en: "", ja: "" },
    };
    expect(localizeName(empty, empty.id, "ja")).toBe("PID Controller");
  });
});

describe("localizeDescription (generic)", () => {
  it("returns locale-specific description when present", () => {
    expect(localizeDescription(PID_ENTRY, "ja")).toBe(
      "PID コントローラ (Kp / Ki / Kd)。",
    );
    expect(localizeDescription(PID_ENTRY, "en")).toBe(
      "PID controller (Kp, Ki, Kd).",
    );
  });

  it("falls back to description when i18n is missing for that locale", () => {
    const partial: LibraryEntryMetadata = {
      ...PID_ENTRY,
      description_i18n: { en: "PID controller (Kp, Ki, Kd)." },
    };
    expect(localizeDescription(partial, "ja")).toBe(
      "PID controller (Kp, Ki, Kd).",
    );
  });

  it("returns empty string when both description and i18n absent", () => {
    const empty: LibraryEntryMetadata = {
      ...PID_ENTRY,
      description: "",
      description_i18n: {},
    };
    expect(localizeDescription(empty, "ja")).toBe("");
  });

  it("works on Library (not just Entry)", () => {
    expect(localizeDescription(STD_LIBRARY, "ja")).toBe("組み込み。");
  });
});
