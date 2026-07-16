// ADR-0024: i18n エントリポイント。``main.tsx`` で副作用 import すると ``i18next``
// が初期化され、以降 ``useTranslation()`` で ``t`` が使えるようになる。
//
// 設計:
//   - 辞書は static import (= ja/en の 2 言語、数十 key で <2KB gzip)
//   - 既定言語: localStorage["flode.lang"] → navigator.language(ja*) → "en"
//   - 永続化: setLanguage(lng) で localStorage に書く
//   - missing key は dev のみ console.warn

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import ja from "./locales/ja.json";

/** サポート言語コード。新言語追加時はここに増やす。 */
export type SupportedLanguage = "en" | "ja";

const SUPPORTED: readonly SupportedLanguage[] = ["en", "ja"] as const;
const STORAGE_KEY = "flode.lang";

/** ``localStorage`` / ``navigator.language`` から起動時の言語を解決する。 */
export function detectInitialLanguage(): SupportedLanguage {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "ja" || stored === "en") return stored;
  } catch {
    // localStorage 不可環境 (= file:// など) は navigator にフォールバック
  }
  const nav =
    typeof navigator !== "undefined" && navigator.language
      ? navigator.language
      : "";
  return nav.toLowerCase().startsWith("ja") ? "ja" : "en";
}

/** 言語切替。``i18next.changeLanguage`` + ``localStorage`` への永続化を行う。 */
export async function setLanguage(lng: SupportedLanguage): Promise<void> {
  if (!SUPPORTED.includes(lng)) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, lng);
  } catch {
    // 保存失敗は致命的でない (= セッション内のみ反映、次回起動で navigator 検出)
  }
  await i18n.changeLanguage(lng);
}

/** 現在の言語コード。``i18next.language`` は ``"en-US"`` のような BCP47 タグに
 * なる場合があるため、``detectInitialLanguage`` と同じ正規化を適用する
 * (= ``"ja*"`` → ``"ja"``、それ以外 → ``"en"``)。これにより Settings > Language
 * のチェックマーク判定が BCP47 タグでも正しく動作する。 */
export function currentLanguage(): SupportedLanguage {
  const lang = i18n.language ?? "";
  return lang.toLowerCase().startsWith("ja") ? "ja" : "en";
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ja: { translation: ja },
    },
    lng: detectInitialLanguage(),
    fallbackLng: "en",
    // i18next 既定の double-brace 補間 ``{{name}}`` を使用 (ICU は採用しない、ADR §7)
    interpolation: {
      escapeValue: false, // React は出力を自動エスケープ
      // ADR-0056 §D-1: 数値 / 配列の locale 表現を frontend 側 formatter に集約。
      // 使い方: ``"{{t, t_sec}}"`` で ``"1.234s"`` 形式、
      // ``"{{block_labels, block_labels}}"`` で ``"a, b, c"`` 連結。
      // 未知 formatter は素通り (= String(value))。
      format: (value, format) => {
        if (format === "t_sec") {
          const n = Number(value);
          return Number.isFinite(n) ? `${n.toFixed(3)}s` : String(value);
        }
        if (format === "block_labels" && Array.isArray(value)) {
          return value.join(", ");
        }
        return String(value);
      },
    },
    saveMissing: import.meta.env.DEV,
    missingKeyHandler: import.meta.env.DEV
      ? (lngs, ns, key) => {
          // dev でだけ console.warn、prod では noop
          // eslint-disable-next-line no-console
          console.warn("[i18n] missing key", { lngs, ns, key });
        }
      : undefined,
    returnNull: false,
  })
  .catch((err) => {
    // eslint-disable-next-line no-console
    console.error("[i18n] init failed", err);
  });

export default i18n;
