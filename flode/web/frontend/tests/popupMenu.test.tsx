// ADR-0081 U4: inspector.tsx の PopupMenu primitive (右クリックメニュー / ⋯ メニュー)。
// Escape・外側の pointerdown・ウィンドウの blur で閉じ、アンカー (開いたボタン) 内の
// pointerdown では閉じない (= ボタン側のトグルと競合しない)。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PopupMenu, PopupMenuItem } from "../src/components/ui/inspector";

function Harness({ onClose }: { onClose: () => void }): JSX.Element {
  const anchorRef = useRef<HTMLButtonElement>(null);
  return (
    <div>
      <button ref={anchorRef} type="button">
        anchor
      </button>
      <button type="button">outside</button>
      <PopupMenu x={10} y={10} onClose={onClose} anchorRef={anchorRef}>
        <PopupMenuItem label="Item" onClick={() => undefined} title="why" />
      </PopupMenu>
    </div>
  );
}

afterEach(() => cleanup());

describe("PopupMenu", () => {
  it("closes on Escape, outside pointerdown and window blur", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.pointerDown(screen.getByText("outside"));
    fireEvent.blur(window);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("does not close on pointerdown inside the menu or the anchor", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.pointerDown(screen.getByRole("menuitem"));
    fireEvent.pointerDown(screen.getByText("anchor"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem").getAttribute("title")).toBe("why");
  });

  it("does not register close handlers without onClose", () => {
    render(
      <PopupMenu x={0} y={0}>
        <PopupMenuItem label="Item" onClick={() => undefined} />
      </PopupMenu>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("menu")).toBeTruthy();
  });
});
