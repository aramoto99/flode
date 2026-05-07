// ADR-0024: i18next の module augmentation で ``t()`` の key 補完と返り値を
// 明示的に string にする (= React の ReactNode 型と衝突する $TFunction の戻り値を
// シンプル string に固定)。
//
// resources は en.json (ja.json と key 集合一致を Vitest で検証) を型 source とする。

import "i18next";
import en from "./locales/en.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: {
      translation: typeof en;
    };
    returnNull: false;
  }
}
