// ADR-0080 §新しいエラーコード: ライブラリ API のエラーコード → 表示文言。

import { beforeAll, describe, expect, it } from "vitest";

import { ApiError } from "../src/api/client";
import i18n from "../src/i18n";
import {
  describeLibraryError,
  describeNameConflict,
  describeWriteDisabledReason,
  entryWriteDisabledReason,
  libraryErrorArgs,
  libraryErrorCode,
  libraryImportDisabledReason,
  libraryReloadDisabledReason,
} from "../src/lib/libraryErrors";
import type { FailurePayload, UserLibraryStatus } from "../src/types/api";

const t = i18n.t.bind(i18n);

/** サーバの構造化エラーと同じ形の ``ApiError`` を作る。 */
function libraryError(
  code: string,
  args: Record<string, unknown> = {},
  status = 409,
): ApiError {
  const structured = {
    category: "library",
    template_key: `error.library.${code}`,
    template_args: { message: `raw ${code}`, ...args },
    raw_message: `raw ${code}`,
    block_id: null,
    block_ids: [],
    block_type: null,
    block_label: null,
    t: null,
    raw_traceback: null,
  } satisfies FailurePayload;
  return new ApiError(status, `${status} raw ${code}`, structured, structured);
}

function status(reason: string, enabled = true): UserLibraryStatus {
  return {
    name: "user",
    enabled,
    exists: false,
    writable: reason === "",
    write_disabled_reason: reason,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("libraryErrorCode / libraryErrorArgs", () => {
  it("extracts the code from the template key", () => {
    const err = libraryError("library_entry_name_conflict", { entry_id: "pid", revision: 2 });
    expect(libraryErrorCode(err)).toBe("library_entry_name_conflict");
    expect(libraryErrorArgs(err)).toMatchObject({ entry_id: "pid", revision: 2 });
  });

  it("returns null for non-library errors", () => {
    expect(libraryErrorCode(new Error("boom"))).toBeNull();
    expect(libraryErrorCode(new ApiError(500, "500 x", null, null))).toBeNull();
    expect(libraryErrorArgs(new Error("boom"))).toEqual({});
  });
});

describe("describeLibraryError", () => {
  const ALL_CODES = [
    "library_write_forbidden",
    "user_library_disabled",
    "library_path_unsafe",
    "library_read_only",
    "library_not_found",
    "library_entry_not_found",
    "library_entry_name_conflict",
    "library_entry_conflict",
    "library_changed_on_disk",
    "user_library_corrupt",
    "library_schema_too_new",
    "library_name_conflict",
    "library_entry_invalid",
    "library_file_invalid",
    "library_write_busy",
    "library_write_failed",
  ];

  it.each(ALL_CODES)("has a translated message for %s in en and ja", async (code) => {
    const err = libraryError(code);
    await i18n.changeLanguage("en");
    const en = describeLibraryError(t, err);
    await i18n.changeLanguage("ja");
    const ja = describeLibraryError(t, err);
    await i18n.changeLanguage("en");
    expect(en).not.toBe("");
    expect(en).not.toContain("error.library.");
    expect(ja).not.toContain("error.library.");
    expect(ja).not.toBe(en);
  });

  it("asks to reload when the file changed on disk", () => {
    const text = describeLibraryError(
      t,
      libraryError("library_changed_on_disk", { path: "C:/lib/user.flwlib.json" }),
    );
    expect(text).toContain("Reload libraries");
    expect(text).toContain("C:/lib/user.flwlib.json");
  });

  it("explains a revision conflict from another tab", () => {
    const text = describeLibraryError(
      t,
      libraryError("library_entry_conflict", {
        entry_id: "pid",
        expected_revision: 2,
        current_revision: 3,
      }),
    );
    expect(text).toContain("another tab");
    expect(text).toContain("rev 2");
    expect(text).toContain("rev 3");
  });

  it("lists the block path and tag for goto_from_not_closed", () => {
    const text = describeLibraryError(
      t,
      libraryError(
        "library_entry_invalid",
        {
          reason: "goto_from_not_closed",
          violations: [
            { path: "inner/from1", tag: "speed", reason: "unresolved_from" },
            { path: "goto1", tag: "bus", reason: "global_goto" },
            { path: "goto2", tag: "dup", reason: "duplicate_goto" },
            { path: "x", tag: "y", reason: "something_new" },
          ],
        },
        422,
      ),
    );
    expect(text).toContain("cannot be added to a library");
    expect(text).toContain('inner/from1 (tag "speed") has no matching Goto');
    expect(text).toContain('goto1 (tag "bus") uses global visibility');
    expect(text).toContain('goto2 (tag "dup") duplicates another Goto tag');
    expect(text).toContain('x (tag "y")');
  });

  it("lists the type names for unknown_types, with the entry id on import", () => {
    const text = describeLibraryError(
      t,
      libraryError(
        "library_entry_invalid",
        { reason: "unknown_types", unknown_types: ["acme.blocks.Foo", "acme.blocks.Bar"], entry_id: "e1" },
        422,
      ),
    );
    expect(text).toContain("acme.blocks.Foo, acme.blocks.Bar");
    expect(text).toContain('Block "e1"');
  });

  it("shows the raw reason for invalid_block and unknown entry reasons", () => {
    expect(
      describeLibraryError(
        t,
        libraryError("library_entry_invalid", { reason: "invalid_block", message: "mask $Kp undeclared" }, 422),
      ),
    ).toContain("mask $Kp undeclared");
    expect(
      describeLibraryError(
        t,
        libraryError("library_entry_invalid", { reason: "brand_new_reason", message: "raw detail" }, 422),
      ),
    ).toContain("raw detail");
  });

  it("falls back to the raw message for unknown file reasons and unknown codes", () => {
    expect(
      describeLibraryError(
        t,
        libraryError("library_file_invalid", { reason: "brand_new_file_reason", message: "entry id is odd" }, 422),
      ),
    ).toContain("entry id is odd");
    expect(describeLibraryError(t, libraryError("library_brand_new", { message: "server says no" }))).toBe(
      "server says no",
    );
  });

  it("explains the file reasons added for import (invalid_metadata / reserved_entry_id)", () => {
    const metadata = describeLibraryError(
      t,
      libraryError(
        "library_file_invalid",
        { reason: "invalid_metadata", field: "display_name", message: "contains control characters" },
        422,
      ),
    );
    expect(metadata).toContain('"display_name"');
    expect(metadata).toContain("contains control characters");
    const reserved = describeLibraryError(
      t,
      libraryError("library_file_invalid", { reason: "reserved_entry_id", entry_id: "export" }, 422),
    );
    expect(reserved).toContain('reserved: "export"');
    // 引数が欠けていても {{...}} がそのまま出ない
    expect(
      describeLibraryError(t, libraryError("library_file_invalid", { reason: "reserved_entry_id" }, 422)),
    ).not.toContain("{{");
  });

  it("names the already-loaded library for uid_exists when the server reports it", () => {
    const text = describeLibraryError(
      t,
      libraryError("library_name_conflict", {
        library: "user-8c1e2f0a",
        reason: "uid_exists",
        conflicts_with: "user",
      }),
    );
    expect(text).toContain('as "user"');
    expect(text).toContain("same library ID");
    // dry-run の conflict に conflicts_with が無い場合は取り込み側の名前で代用
    expect(describeNameConflict(t, "acme", "uid_exists")).toContain('as "acme"');
  });

  it("explains body-size rejections that come back as plain (non-structured) errors", () => {
    const tooLarge = describeLibraryError(t, new ApiError(413, "413 Request body exceeds", null, "x"));
    const noLength = describeLibraryError(t, new ApiError(411, "411 Length Required", null, "x"));
    expect(tooLarge).toContain("too large");
    expect(noLength).toContain("size of the request");
    // それ以外の非構造化エラーは従来どおり message
    expect(describeLibraryError(t, new ApiError(500, "500 boom", null, null))).toBe("500 boom");
  });

  it("mentions the backup only when one exists", () => {
    const withBackup = describeLibraryError(
      t,
      libraryError("user_library_corrupt", { path: "p", reason: "bad json", has_backup: true }),
    );
    const without = describeLibraryError(
      t,
      libraryError("user_library_corrupt", { path: "p", reason: "bad json", has_backup: false }),
    );
    expect(withBackup).toContain(".bak");
    expect(without).not.toContain(".bak");
  });

  it("distinguishes name conflict reasons (reserved / exists / uid_exists)", () => {
    const reserved = describeNameConflict(t, "user", "reserved");
    const exists = describeNameConflict(t, "acme", "exists");
    const uid = describeNameConflict(t, "user-8c1e2f0a", "uid_exists");
    expect(reserved).toContain("reserved");
    expect(exists).toContain("already loaded");
    expect(uid).toContain("same library ID");
    expect(new Set([reserved, exists, uid]).size).toBe(3);
    // 409 経由でも同じ文言
    expect(
      describeLibraryError(t, libraryError("library_name_conflict", { library: "acme", reason: "exists" })),
    ).toBe(exists);
    // 未知の reason は exists 扱い
    expect(describeNameConflict(t, "acme", "future_reason")).toBe(exists);
  });

  it("clips and flattens untrusted strings from the server", () => {
    const text = describeLibraryError(
      t,
      libraryError("library_write_failed", { message: `line1\nline2\u202Eevil ${"x".repeat(1000)}` }),
    );
    expect(text).not.toContain("\n");
    expect(text).not.toContain("\u202E");
    expect(text.length).toBeLessThan(400);
    expect(text.endsWith("…")).toBe(true);
  });

  it("returns the plain message for non-library errors", () => {
    expect(describeLibraryError(t, new Error("network down"))).toBe("network down");
  });
});

describe("write-disabled reasons", () => {
  it("translates each write_disabled_reason and returns undefined when writable", () => {
    expect(describeWriteDisabledReason(t, "")).toBeUndefined();
    for (const reason of [
      "library_write_forbidden",
      "user_library_disabled",
      "user_library_corrupt",
      "library_schema_too_new",
      "library_read_only",
    ]) {
      const text = describeWriteDisabledReason(t, reason);
      expect(text).toBeTruthy();
      expect(text).not.toContain("library.write_disabled.");
    }
    expect(describeWriteDisabledReason(t, "future_reason")).toBe("future_reason");
  });

  it("entry writes follow user_library.writable", () => {
    expect(entryWriteDisabledReason(undefined)).toBe("");
    expect(entryWriteDisabledReason(status(""))).toBe("");
    expect(entryWriteDisabledReason(status("user_library_corrupt"))).toBe("user_library_corrupt");
  });

  it("reload is blocked only when the server forbids library writes", () => {
    expect(libraryReloadDisabledReason(status(""))).toBe("");
    expect(libraryReloadDisabledReason(status("user_library_disabled", false))).toBe("");
    expect(libraryReloadDisabledReason(status("user_library_corrupt"))).toBe("");
    expect(libraryReloadDisabledReason(status("library_write_forbidden", false))).toBe(
      "library_write_forbidden",
    );
  });

  it("import needs write permission and an enabled user library, not a healthy file", () => {
    expect(libraryImportDisabledReason(status(""))).toBe("");
    expect(libraryImportDisabledReason(status("user_library_corrupt"))).toBe("");
    expect(libraryImportDisabledReason(status("library_schema_too_new"))).toBe("");
    expect(libraryImportDisabledReason(status("user_library_disabled", false))).toBe(
      "user_library_disabled",
    );
    expect(libraryImportDisabledReason(status("library_write_forbidden"))).toBe(
      "library_write_forbidden",
    );
  });
});
