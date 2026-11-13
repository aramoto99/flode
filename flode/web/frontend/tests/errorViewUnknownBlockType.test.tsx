// ADR-0081 §4-B (U4): 実行要求の 400 ``unknown_block_type`` を既存のエラー表示 (ログタブの
// ErrorView) で i18n 文言として出す。型名・ブロック id は信頼できない文字列として整形する。

import i18n from "../src/i18n";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { ErrorView } from "../src/components/ErrorView";
import { useAppStore } from "../src/store/appStore";
import type { FailurePayload } from "../src/types/api";

const RLO = String.fromCharCode(0x202e);

function payload(truncated: boolean): FailurePayload {
  return {
    category: "unknown_block_type",
    template_key: "error.unknown_block_type",
    template_args: {
      types: [`flode_ws.filters.Gone${RLO}`, "flode_ws.io.Old"],
      blocks: [],
      block_labels: ["a", "sub/b"],
      truncated,
      message: "The model uses block types that are not loaded",
    },
    block_id: "a",
    block_ids: ["a", "b"],
    block_type: "flode_ws.filters.Gone",
    block_label: "a",
    t: null,
    raw_message: "The model uses block types that are not loaded",
    raw_traceback: null,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  cleanup();
  useAppStore.getState().setLastFailure(null, "start");
});

describe("ErrorView: unknown_block_type", () => {
  it("renders the i18n text with all missing types and blocks", () => {
    useAppStore.getState().setLastFailure(payload(false), "start");
    render(<ErrorView />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(
      "The model uses block types that are not loaded: flode_ws.filters.Gone, flode_ws.io.Old.",
    );
    expect(alert.textContent).toContain("remove these blocks: a, sub/b");
    expect(alert.textContent).not.toContain(RLO);
    expect(alert.textContent).not.toContain("(and more)");
  });

  it("adds the 'and more' note when the server truncated the list", () => {
    useAppStore.getState().setLastFailure(payload(true), "start");
    render(<ErrorView />);
    expect(screen.getByRole("alert").textContent).toContain("(and more)");
  });
});
