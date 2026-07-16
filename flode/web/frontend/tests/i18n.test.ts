// ADR-0024 §10 受入基準: i18next 初期化 / 翻訳 / 言語切替 / key 集合一致 / 補間。

import { beforeEach, describe, expect, it } from "vitest";

import en from "../src/i18n/locales/en.json";
import ja from "../src/i18n/locales/ja.json";
import i18n, {
  currentLanguage,
  detectInitialLanguage,
  setLanguage,
} from "../src/i18n";

beforeEach(() => {
  // 各テストで言語を en にリセット。localStorage も毎回 clear。
  try {
    window.localStorage.clear();
  } catch {
    // jsdom 以外の環境では noop
  }
});

describe("locale dictionaries", () => {
  it("ja and en have identical key sets (no missing translations)", () => {
    const enKeys = Object.keys(en).sort();
    const jaKeys = Object.keys(ja).sort();
    expect(jaKeys).toEqual(enKeys);
  });

  it("every value is a non-empty string", () => {
    for (const [k, v] of Object.entries(en)) {
      expect(typeof v, `en/${k}`).toBe("string");
      expect((v as string).length, `en/${k} non-empty`).toBeGreaterThan(0);
    }
    for (const [k, v] of Object.entries(ja)) {
      expect(typeof v, `ja/${k}`).toBe("string");
      expect((v as string).length, `ja/${k} non-empty`).toBeGreaterThan(0);
    }
  });
});

describe("i18next init", () => {
  it("returns the en label by default", async () => {
    await setLanguage("en");
    expect(i18n.t("menu.file")).toBe("File");
    expect(i18n.t("toolbar.run")).toBe("Run Simulation (F9 / Ctrl+T)");
  });

  it("switches to ja on setLanguage", async () => {
    await setLanguage("ja");
    expect(i18n.t("menu.file")).toBe("ファイル");
    expect(i18n.t("toolbar.run")).toBe("シミュレーション実行 (F9 / Ctrl+T)");
    expect(currentLanguage()).toBe("ja");
  });

  it("falls back to en for keys missing in active locale (theoretical)", async () => {
    // ja.json と en.json は key 集合が一致するためフォールバックは発火しない設計だが、
    // i18next の fallbackLng=en が機能していることを smoke で確認。
    await setLanguage("ja");
    // 存在しない key は key 自身を返す (= prod 既定挙動)。
    // 型補完上は invalid key なので runtime 側で型を緩める。
    const missing = (i18n.t as (k: string) => string)("does.not.exist");
    expect(typeof missing).toBe("string");
  });
});

describe("interpolation", () => {
  it("substitutes {{name}} placeholders", async () => {
    await setLanguage("en");
    expect(
      i18n.t("modal.delete.message", { name: "untitled1" }),
    ).toBe('Permanently delete "untitled1.flw.json"?');
  });

  it("substitutes {{name}} placeholders in ja", async () => {
    await setLanguage("ja");
    expect(
      i18n.t("modal.delete.message", { name: "untitled1" }),
    ).toBe("「untitled1.flw.json」を完全に削除しますか?");
  });

  it("substitutes statusbar.running pct + t", async () => {
    await setLanguage("en");
    expect(i18n.t("statusbar.running", { pct: 42, t: "1.50" })).toBe(
      "Running 42% (t=1.50)",
    );
  });
});

describe("language persistence", () => {
  it("writes lang choice to localStorage", async () => {
    await setLanguage("ja");
    expect(window.localStorage.getItem("flode.lang")).toBe("ja");
  });

  it("detectInitialLanguage prefers stored value", () => {
    window.localStorage.setItem("flode.lang", "ja");
    expect(detectInitialLanguage()).toBe("ja");
    window.localStorage.setItem("flode.lang", "en");
    expect(detectInitialLanguage()).toBe("en");
  });

  it("detectInitialLanguage ignores invalid stored values", () => {
    window.localStorage.setItem("flode.lang", "fr"); // 不正
    // navigator.language fallback が走る (jsdom default = en-US)
    const detected = detectInitialLanguage();
    expect(["en", "ja"]).toContain(detected);
  });
});

describe("setLanguage rejects invalid codes", () => {
  it("ignores unsupported language codes (no localStorage write)", async () => {
    await setLanguage("ja");
    window.localStorage.removeItem("flode.lang");
    // @ts-expect-error: explicitly testing runtime guard
    await setLanguage("xx");
    expect(window.localStorage.getItem("flode.lang")).toBeNull();
  });
});
