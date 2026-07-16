// ADR-0056 §F5: ErrorView の描画と振る舞いをテスト。
//
// カバレッジ:
//   * lastFailure === null → 空文言
//   * lastFailure あり → プレフィックス + テンプレートレンダリング (i18n formatter 経由)
//   * block_ids が複数 → 複数チップが出る
//   * 「Diagram で表示」クリックで setSelectedNodeIds が呼ばれる
//   * 詳細 (traceback) 折り畳み + コピー
//   * 未知 template_key は ``error.unknown`` に fallback

import i18n from "../src/i18n"; // i18next 初期化 (= interpolation.format formatter を有効化)

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorView } from "../src/components/ErrorView";
import { useAppStore } from "../src/store/appStore";
import type { FailurePayload } from "../src/types/api";

// jsdom 環境では navigator.language が "en-US" 等になり i18next が en に倒れる。
// 本テストは ja 文言を assert するため、明示的に ja に切り替える。
beforeAll(async () => {
  await i18n.changeLanguage("ja");
});

const _BASE: FailurePayload = {
  category: "divide_by_zero",
  template_key: "error.divide_by_zero",
  template_args: { block_label: "Divide1", t: 1.234 },
  block_id: "blk_div",
  block_ids: ["blk_div"],
  block_type: "pyflw.blocks.mathops.Divide",
  block_label: "Divide1",
  t: 1.234,
  raw_message: "ZeroDivisionError: float division by zero",
  raw_traceback: "Traceback (most recent call last):\n  File ...\n",
};

function _setFailure(
  payload: FailurePayload | null,
  source: "start" | "runtime" = "runtime",
): void {
  useAppStore.getState().setLastFailure(payload, source);
}

beforeEach(() => {
  // 各 test で store を初期状態に近づける。setLastFailure(null,...) で clear。
  _setFailure(null);
});

afterEach(() => {
  cleanup();
  _setFailure(null);
});

describe("ErrorView", () => {
  it("renders empty message when lastFailure is null", () => {
    render(<ErrorView />);
    expect(screen.getByText("ログはまだありません")).toBeTruthy();
  });

  it("renders runtime failure with i18n template (block_label + t_sec formatter)", () => {
    _setFailure(_BASE, "runtime");
    render(<ErrorView />);
    // "Divide1" は本文中でインラインリンク (button) に分離される。
    expect(screen.getByRole("button", { name: "Divide1" })).toBeTruthy();
    // リンク以外の本文部分 (= t_sec formatter 適用後)。
    expect(screen.getByText(/ブロックで 0 除算 \(t=1\.234s\)/)).toBeTruthy();
    expect(screen.getByText(/実行中エラー:/)).toBeTruthy();
  });

  it("renders start failure with start prefix", () => {
    _setFailure(_BASE, "start");
    render(<ErrorView />);
    expect(screen.getByText(/起動失敗:/)).toBeTruthy();
  });

  it("renders multiple block chips for algebraic_loop", () => {
    const loop: FailurePayload = {
      ..._BASE,
      category: "algebraic_loop",
      template_key: "error.algebraic_loop",
      template_args: { block_labels: ["a", "b", "c"] },
      block_id: "a",
      block_ids: ["a", "b", "c"],
      block_label: "a",
      t: null,
    };
    _setFailure(loop, "runtime");
    render(<ErrorView />);
    expect(screen.getByText(/関与ブロック: a, b, c/)).toBeTruthy();
    // 3 つのチップが出る
    expect(screen.getByRole("button", { name: "a" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "b" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "c" })).toBeTruthy();
  });

  it("shows a fallback chip when the single block is not inline-linked", () => {
    // solver_failure はメッセージ本文にブロック名が出ない (= t / reason のみ) ため
    // インラインリンクが張れない。単一ブロックでもフォールバックのチップを出す。
    const payload: FailurePayload = {
      ..._BASE,
      category: "solver_failure",
      template_key: "error.solver_failure",
      template_args: { t: 0.5, reason: "max_step" },
      block_label: "IntegratorX",
      block_id: "int_x",
      block_ids: ["int_x"],
      t: 0.5,
    };
    _setFailure(payload, "runtime");
    const spy = vi.spyOn(useAppStore.getState(), "focusBlock");
    render(<ErrorView />);
    fireEvent.click(screen.getByRole("button", { name: "int_x" }));
    expect(spy).toHaveBeenCalledWith("int_x");
  });

  it("does NOT show a redundant chip when the block is inline-linked", () => {
    // _BASE = divide_by_zero、本文に "Divide1" が出るのでインラインリンクのみ。
    _setFailure(_BASE, "runtime");
    render(<ErrorView />);
    // "Divide1" のリンクは 1 つだけ (= チップで重複しない)。
    expect(screen.getAllByRole("button", { name: "Divide1" })).toHaveLength(1);
  });

  it("clicking the inline block-name link jumps to that block", () => {
    _setFailure(_BASE, "runtime");
    const spy = vi.spyOn(useAppStore.getState(), "focusBlock");
    render(<ErrorView />);
    // 本文 "Divide1 ブロックで 0 除算 ..." の "Divide1" がリンク (button)。
    fireEvent.click(screen.getByRole("button", { name: "Divide1" }));
    expect(spy).toHaveBeenCalledWith("blk_div");
  });

  it("clicking a block chip jumps to that block", () => {
    const loop: FailurePayload = {
      ..._BASE,
      category: "algebraic_loop",
      template_key: "error.algebraic_loop",
      template_args: { block_labels: ["a", "b"] },
      block_id: "a",
      block_ids: ["a", "b"],
      block_label: "a",
      t: null,
    };
    _setFailure(loop, "runtime");
    const spy = vi.spyOn(useAppStore.getState(), "focusBlock");
    render(<ErrorView />);
    fireEvent.click(screen.getByRole("button", { name: "b" }));
    expect(spy).toHaveBeenCalledWith("b");
  });

  it("falls back to error.unknown for unrecognized template_key", () => {
    const unknown: FailurePayload = {
      ..._BASE,
      category: "future_category",
      template_key: "error.totally_made_up",
      template_args: { raw_message: "Mystery!" },
      t: null,
    };
    _setFailure(unknown, "runtime");
    render(<ErrorView />);
    // unknown fallback は raw_message を露出する
    expect(screen.getByText(/Mystery!/)).toBeTruthy();
  });

  it("opens traceback details on summary click", () => {
    _setFailure(_BASE, "runtime");
    render(<ErrorView />);
    const summary = screen.getByText("詳細 (traceback)");
    fireEvent.click(summary);
    // <pre> 内に traceback テキストが見える
    expect(
      screen.getByText(/Traceback \(most recent call last\)/),
    ).toBeTruthy();
  });

  it("clicking 'コピー' calls navigator.clipboard.writeText with traceback", () => {
    // code-reviewer SHOULD-4: jsdom にはデフォルト clipboard が無いため stub。
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    _setFailure(_BASE, "runtime");
    render(<ErrorView />);
    // 折り畳みを開く必要あり (= コピーボタンは details 内)
    fireEvent.click(screen.getByText("詳細 (traceback)"));
    fireEvent.click(screen.getByRole("button", { name: "コピー" }));
    expect(writeText).toHaveBeenCalledWith(_BASE.raw_traceback);
    vi.unstubAllGlobals();
  });
});
