// ADR-0086 §6-A, SPEC-0037 U-10 / D7 / 受け入れ条件 4: 「テキストで編集…」。
// - TextListEditor は 1 行 1 項目の textarea (引用符なし)
// - OK で前後の空白を削り空行を捨てた行のリストを渡す。キャンセルでは何も渡さない

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts !== undefined ? `${k}:${JSON.stringify(opts)}` : k,
  }),
}));

import { ParamRowsTextDialog } from "../src/components/ParamRowsTextDialog";
import { TextListEditor } from "../src/components/ui/inspector";

afterEach(() => cleanup());

describe("TextListEditor", () => {
  it("is a plain textarea bound to the text", () => {
    function Harness(): JSX.Element {
      const [text, setText] = useState("a\nb");
      return (
        <>
          <TextListEditor value={text} onChange={setText} testId="ed" />
          <output data-testid="out">{text}</output>
        </>
      );
    }
    render(<Harness />);
    const ed = screen.getByTestId("ed") as HTMLTextAreaElement;
    expect(ed.tagName).toBe("TEXTAREA");
    expect(ed.value).toBe("a\nb");
    fireEvent.change(ed, { target: { value: "x\ny\n" } });
    expect(screen.getByTestId("out").textContent).toBe("x\ny\n");
  });
});

describe("ParamRowsTextDialog", () => {
  it("shows one row per line and returns trimmed non-blank rows on OK", () => {
    const onOk = vi.fn();
    render(
      <ParamRowsTextDialog
        param="parts"
        initialRows={["a: bolt", "b: nut"]}
        onOk={onOk}
        onClose={() => undefined}
      />,
    );
    const ed = screen.getByTestId("param-rows-text-input") as HTMLTextAreaElement;
    expect(ed.value).toBe("a: bolt\nb: nut");
    fireEvent.change(ed, { target: { value: "  a: bolt  \n\n   \nc: pin\n" } });
    expect(screen.getByTestId("param-rows-text-count").textContent).toContain('"count":2');
    fireEvent.click(screen.getByTestId("param-rows-text-ok"));
    expect(onOk).toHaveBeenCalledWith(["a: bolt", "c: pin"]);
  });

  it("cancel changes nothing", () => {
    const onOk = vi.fn();
    const onClose = vi.fn();
    render(
      <ParamRowsTextDialog param="parts" initialRows={["a"]} onOk={onOk} onClose={onClose} />,
    );
    fireEvent.change(screen.getByTestId("param-rows-text-input"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("param-rows-text-cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(onOk).not.toHaveBeenCalled();
  });
});
