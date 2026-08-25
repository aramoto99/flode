// ADR-0071: block id 検証の Python / TypeScript 等価性テスト。
// 共有ケース表 tests/data/block_id_cases.json (repo root) を読み、
// validateBlockId の判定が Python 側 validate_block_id と一致することを検証する。
// 規則がどちらかで変わると、このテストか tests/core/test_identifiers.py が落ちる。

import { describe, expect, it } from "vitest";

import rawTable from "../../../../tests/data/block_id_cases.json";
import {
  BLOCK_ID_MAX_LEN,
  foldBlockId,
  isReservedWord,
  normalizeBlockId,
  validateBlockId,
} from "../src/lib/idGenerator";

interface IdCase {
  id: string;
  valid: boolean;
  keyword?: boolean;
  note: string;
}
interface IdPair {
  a: string;
  b: string;
  note: string;
}
const table = rawTable as unknown as {
  cases: IdCase[];
  fold_conflicts: IdPair[];
  fold_distinct: IdPair[];
};

const NO_SIBLINGS = new Set<string>();

describe("validateBlockId — 共有ケース表との一致 (ADR-0071 §(9))", () => {
  for (const c of table.cases) {
    it(`${JSON.stringify(c.id).slice(0, 40)} → ${c.valid ? "valid" : "invalid"} (${c.note})`, () => {
      const result = validateBlockId(c.id, NO_SIBLINGS);
      if (c.valid) {
        expect(result).toBeNull();
      } else {
        expect(result).not.toBeNull();
      }
    });
  }

  it("keyword ケースは valid かつ isReservedWord=true", () => {
    for (const c of table.cases.filter((c) => c.keyword)) {
      expect(validateBlockId(c.id, NO_SIBLINGS)).toBeNull();
      expect(isReservedWord(c.id)).toBe(true);
    }
    expect(isReservedWord("速度指令")).toBe(false);
  });
});

describe("foldBlockId — NFKC fold key (ADR-0071 §(2))", () => {
  for (const p of table.fold_conflicts) {
    it(`衝突: ${p.note}`, () => {
      expect(foldBlockId(p.a)).toBe(foldBlockId(p.b));
    });
  }
  for (const p of table.fold_distinct) {
    it(`非衝突: ${p.note}`, () => {
      expect(foldBlockId(p.a)).not.toBe(foldBlockId(p.b));
    });
  }
});

describe("validateBlockId — 重複判定", () => {
  it("完全一致は duplicate", () => {
    expect(validateBlockId("Gain_0", new Set(["Gain_0"]))).toBe("duplicate");
  });
  it("自分自身 (currentId) は重複とみなさない", () => {
    expect(validateBlockId("Gain_0", new Set(["Gain_0"]), "Gain_0")).toBeNull();
  });
  it("NFKC fold 衝突は confusable_duplicate", () => {
    expect(validateBlockId("Gain_１", new Set(["Gain_1"]))).toBe(
      "confusable_duplicate",
    );
  });
  it("fold 衝突相手が自分自身なら OK (NFC 同一形は duplicate 側で先に判定)", () => {
    expect(validateBlockId("ｿｸﾄﾞ", new Set(["ｿｸﾄﾞ"]), "ｿｸﾄﾞ")).toBeNull();
  });
});

describe("normalizeBlockId — NFC 正規化 (ADR-0071 §(3))", () => {
  it("NFD 入力を NFC に畳む", () => {
    const nfd = "がいん"; // か + 結合濁点 + いん
    const nfc = normalizeBlockId(nfd);
    expect(nfc).toBe("がいん"); // がいん (合成済)
    expect(validateBlockId(nfd, NO_SIBLINGS)).toBe("not_normalized");
    expect(validateBlockId(nfc, NO_SIBLINGS)).toBeNull();
  });
  it("ASCII は恒等", () => {
    expect(normalizeBlockId("Gain_0")).toBe("Gain_0");
  });
});

describe("BLOCK_ID_MAX_LEN", () => {
  it("64 code points ちょうどは valid、65 は too_long (絵文字 = 1 code point x2)", () => {
    expect(validateBlockId("あ".repeat(BLOCK_ID_MAX_LEN), NO_SIBLINGS)).toBeNull();
    expect(validateBlockId("あ".repeat(BLOCK_ID_MAX_LEN + 1), NO_SIBLINGS)).toBe(
      "too_long",
    );
  });
});
