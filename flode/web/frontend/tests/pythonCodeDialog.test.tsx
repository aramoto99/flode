// SPEC-0023: PythonCodeDialog — 適用時に introspect を通し、失敗なら閉じない。

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PythonFunctionIntrospectResponse } from "../src/types/api";

const introspectMock = vi.fn<() => Promise<PythonFunctionIntrospectResponse>>();
vi.mock("../src/api/client", () => ({
  introspectPythonFunctions: () => introspectMock(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts && "lineno" in opts ? `L${String(opts.lineno)}: ${String(opts.message)}` : k,
  }),
}));

import { PythonCodeDialog } from "../src/components/PythonCodeDialog";
import { _resetPythonSpecCacheForTest, getCachedPythonSpec } from "../src/lib/pythonFunctionSpec";

const OK_SPEC = {
  resolved: true as const,
  func_name: "f",
  n_inputs: 1,
  n_outputs: 1,
  n_states: 0,
  direct_feedthrough: true,
  sample_time: null,
  params_spec: [],
};

beforeEach(() => {
  _resetPythonSpecCacheForTest();
  introspectMock.mockReset();
});
afterEach(() => cleanup());

describe("PythonCodeDialog", () => {
  it("shows a line-numbered error and stays open when analysis fails", async () => {
    introspectMock.mockResolvedValue({
      results: { k: { resolved: false, error: { message: "syntax error: x", lineno: 2, col: 5, kind: "syntax" } } },
    });
    const onApply = vi.fn();
    const onClose = vi.fn();
    render(<PythonCodeDialog initialCode="@block\ndef f(" onApply={onApply} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("python-code-apply"));
    await waitFor(() => expect(screen.getByTestId("python-code-error")).toBeTruthy());
    expect(screen.getByTestId("python-code-error").textContent).toBe("L2: syntax error: x");
    expect(onApply).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("caches the spec and calls onApply with the edited code on success", async () => {
    introspectMock.mockResolvedValue({ results: { k: OK_SPEC } });
    const onApply = vi.fn();
    render(<PythonCodeDialog initialCode="old" onApply={onApply} onClose={vi.fn()} />);
    const ta = screen.getByTestId("python-code-textarea") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "new code" } });
    fireEvent.click(screen.getByTestId("python-code-apply"));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith("new code", OK_SPEC));
    expect(getCachedPythonSpec("new code")).toEqual(OK_SPEC);
  });

  it("inserts 4 spaces on Tab instead of moving focus", () => {
    render(<PythonCodeDialog initialCode="ab" onApply={vi.fn()} onClose={vi.fn()} />);
    const ta = screen.getByTestId("python-code-textarea") as HTMLTextAreaElement;
    ta.setSelectionRange(1, 1);
    fireEvent.keyDown(ta, { key: "Tab" });
    expect(ta.value).toBe("a    b");
  });

  it("cancel closes without applying", () => {
    const onClose = vi.fn();
    render(<PythonCodeDialog initialCode="x" onApply={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("python-code-cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(introspectMock).not.toHaveBeenCalled();
  });
});
