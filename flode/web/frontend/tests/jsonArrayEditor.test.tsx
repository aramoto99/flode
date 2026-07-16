// SPEC-0011 §テスト戦略: JsonArrayEditor primitive の単体テスト。
//
// 検証ポリシー (SPEC §1.1):
// - blur 時に JSON.parse + Array.isArray + 要素型一致を検証
// - 失敗時は inline error 表示、onCommit は呼ばない
// - 成功時は parsed value を onCommit に渡す

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JsonArrayEditor } from "../src/components/ui/inspector";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, string> | string) => {
      // テストでは key + 引数を結合した文字列を返し、検証時に key で判定する
      if (typeof params === "object" && params !== null) {
        return `${k}|${JSON.stringify(params)}`;
      }
      return k;
    },
  }),
}));

afterEach(() => cleanup());

function blurTextarea(testid: string, newValue: string): void {
  const ta = screen.getByTestId(testid) as HTMLTextAreaElement;
  fireEvent.change(ta, { target: { value: newValue } });
  fireEvent.blur(ta);
}

describe("JsonArrayEditor", () => {
  it("commits parsed array on blur (number)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0, 1]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", "[1.0, 2.0, 3.0]");
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith([1.0, 2.0, 3.0]);
    expect(screen.queryByTestId("arr-error")).toBeNull();
  });

  it("commits parsed array on blur (string)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={["a", "b"]}
        elementType="string"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", '["x", "y", "z"]');
    expect(onCommit).toHaveBeenCalledWith(["x", "y", "z"]);
  });

  it("commits empty array on blur (Lookup default boundary)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0, 1]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", "[]");
    // SPEC §エッジケース: 空配列も commit、block __init__ 側で BlockSpecError
    expect(onCommit).toHaveBeenCalledWith([]);
  });

  it("shows parse_error and does not commit on invalid JSON", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", "[0, 1,]"); // trailing comma
    expect(onCommit).not.toHaveBeenCalled();
    const err = screen.getByTestId("arr-error");
    expect(err.textContent).toContain("inspector.array.parse_error");
  });

  it("shows not_array error when JSON parses but is not an array", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", "123");
    expect(onCommit).not.toHaveBeenCalled();
    const err = screen.getByTestId("arr-error");
    expect(err.textContent).toContain("inspector.array.not_array");
  });

  it("shows element_type error for mixed number/string (elementType=number)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", '[1, "x", 2]');
    expect(onCommit).not.toHaveBeenCalled();
    const err = screen.getByTestId("arr-error");
    expect(err.textContent).toContain("inspector.array.element_type");
    expect(err.textContent).toContain('"expected":"number"');
  });

  it("shows element_type error for mixed string/number (elementType=string)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={["a"]}
        elementType="string"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", '["a", 1]');
    expect(onCommit).not.toHaveBeenCalled();
    const err = screen.getByTestId("arr-error");
    expect(err.textContent).toContain("inspector.array.element_type");
    expect(err.textContent).toContain('"expected":"string"');
  });

  it("rejects nan / infinity element (number elementType)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    // JSON は NaN / Infinity をサポートしないが、`null` を含むと typeof check が落ちる
    blurTextarea("arr", "[1, null, 3]");
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("clears error after recovery (invalid → valid)", () => {
    const onCommit = vi.fn();
    render(
      <JsonArrayEditor
        value={[0]}
        elementType="number"
        testid="arr"
        onCommit={onCommit}
      />,
    );
    blurTextarea("arr", "[0, 1,]"); // error
    expect(screen.getByTestId("arr-error")).toBeTruthy();
    blurTextarea("arr", "[0, 1, 2]"); // recovery
    expect(screen.queryByTestId("arr-error")).toBeNull();
    expect(onCommit).toHaveBeenCalledWith([0, 1, 2]);
  });
});
