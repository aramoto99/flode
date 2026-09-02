// SPEC-0024 / ADR-0074 §論点 7: PythonFunctionEditor の構造編集 (rewrite フロー)。
// - commit は rewrite → putPythonSpec → updateBlockParams の順 (剪定ガード V14)
// - applied:false / 通信失敗は inline error + draft ロールバック、params 不変
// - base code 不一致の応答は破棄 (stale)
// - editable.inputs:false は disabled + hint
// - IME composition 中の Enter では commit しない / busy 中の連打は 1 回だけ

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  FlwModel,
  PythonFunctionRewriteResponse,
  PythonFunctionSpec,
} from "../src/types/api";

const rewriteMock = vi.fn<() => Promise<PythonFunctionRewriteResponse>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ blocks: [] })),
    introspectPythonFunctions: vi.fn(async () => ({ results: {} })),
    rewritePythonFunction: (...args: unknown[]) => rewriteMock(...(args as [])),
  };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts && "message" in opts ? `${k}:${String(opts.message)}` : k,
  }),
}));

import { PythonFunctionEditor } from "../src/components/PythonFunctionEditor";
import {
  _resetPythonSpecCacheForTest,
  getCachedPythonSpec,
  putPythonSpec,
} from "../src/lib/pythonFunctionSpec";
import { useAppStore } from "../src/store/appStore";

const CODE = "@block\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n";
const NEW_CODE =
  "@block\ndef f(t: float, u: tuple[float, float, float]) -> float:\n    return u[0]\n";

function spec(over: Partial<PythonFunctionSpec> = {}): PythonFunctionSpec {
  return {
    resolved: true,
    func_name: "f",
    n_inputs: 2,
    n_outputs: 1,
    n_states: 0,
    direct_feedthrough: true,
    sample_time: null,
    params_spec: [],
    input_names: [],
    output_names: [],
    editable: {
      inputs: true,
      outputs: true,
      min_inputs: 1,
      max_inputs: 32,
      min_outputs: 1,
      max_outputs: 32,
    },
    ...over,
  };
}

function model(code = CODE): FlwModel {
  return {
    schema_version: "0.10",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [{ id: "pf", type: "flode.blocks.pythonfunc.PythonFunction", params: { code, user_params: {} } }],
    connections: [],
    layout: {},
  } as unknown as FlwModel;
}

function pfParams(): Record<string, unknown> {
  const m = useAppStore.getState().editingModel;
  const b = (m?.blocks ?? []).find((x) => x.id === "pf");
  return (b?.params ?? {}) as Record<string, unknown>;
}

function renderEditor(code = CODE) {
  useAppStore.setState({ editingModel: model(code), editingPath: [], selectedNodeId: "pf" });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const block = { id: "pf", type: "flode.blocks.pythonfunc.PythonFunction", params: { code, user_params: {} } };
  return render(
    <QueryClientProvider client={qc}>
      <PythonFunctionEditor block={block} header={<div />} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  _resetPythonSpecCacheForTest();
  rewriteMock.mockReset();
});
afterEach(() => cleanup());

describe("PythonFunctionEditor 構造編集 (SPEC-0024)", () => {
  it("入力数 commit → rewrite → cache 投入 → params 更新 (剪定ガード順)", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({
      applied: true,
      code: NEW_CODE,
      spec: spec({ n_inputs: 3 }),
    });
    renderEditor();
    const input = screen.getByTestId("pf-n-inputs-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.blur(input);
    await waitFor(() => expect(pfParams().code).toBe(NEW_CODE));
    // V14: params が更新された時点で新コードの spec は cache 済み (剪定ガード成立)
    expect(getCachedPythonSpec(NEW_CODE)?.resolved).toBe(true);
    expect(rewriteMock).toHaveBeenCalledWith(CODE, { inputs: 3 });
  });

  it("ポート名 commit → rewrite に全行の名前列を渡す", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({ applied: true, code: NEW_CODE, spec: spec({ input_names: ["速度指令", ""] }) });
    renderEditor();
    const name0 = screen.getByTestId("pf-in-name-0") as HTMLInputElement;
    fireEvent.change(name0, { target: { value: "速度指令" } });
    fireEvent.blur(name0);
    await waitFor(() =>
      expect(rewriteMock).toHaveBeenCalledWith(CODE, { input_names: ["速度指令", ""] }),
    );
  });

  it("applied:false は inline error + draft ロールバック + params 不変", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({
      applied: false,
      error: { message: "cannot rewrite", lineno: 2, col: null, kind: "unsupported" },
    });
    renderEditor();
    const input = screen.getByTestId("pf-n-inputs-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.getByTestId("pf-struct-error")).toBeTruthy());
    expect(pfParams().code).toBe(CODE);
    expect(input.value).toBe("2"); // ロールバック
  });

  it("通信失敗も inline error + ロールバック", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockRejectedValue(new Error("boom"));
    renderEditor();
    const input = screen.getByTestId("pf-n-inputs-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.getByTestId("pf-struct-error").textContent).toContain("boom"));
    expect(pfParams().code).toBe(CODE);
  });

  it("base code が変わった応答は破棄する (stale)", async () => {
    putPythonSpec(CODE, spec());
    let resolve!: (r: PythonFunctionRewriteResponse) => void;
    rewriteMock.mockReturnValue(new Promise((res) => (resolve = res)));
    renderEditor();
    const input = screen.getByTestId("pf-n-inputs-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.blur(input);
    // 別経路 (dialog 等) でコードが変わったことを再現
    useAppStore.setState({ editingModel: model("changed-code") });
    resolve({ applied: true, code: NEW_CODE, spec: spec({ n_inputs: 3 }) });
    await waitFor(() =>
      expect(screen.getByTestId("pf-struct-error").textContent).toContain("rewrite_stale"),
    );
    // 破棄された = NEW_CODE は書き込まれていない
    expect(pfParams().code).toBe("changed-code");
  });

  it("editable.inputs:false は disabled + hint (u 無し関数)", () => {
    putPythonSpec(CODE, spec({ n_inputs: 0, editable: { ...spec().editable, inputs: false, min_inputs: 0 } }));
    renderEditor();
    expect((screen.getByTestId("pf-n-inputs-input") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByTestId("pf-inputs-locked-hint")).toBeTruthy();
  });

  it("busy 中の連打は 1 回だけ rewrite する", async () => {
    putPythonSpec(CODE, spec());
    let resolve!: (r: PythonFunctionRewriteResponse) => void;
    rewriteMock.mockReturnValue(new Promise((res) => (resolve = res)));
    renderEditor();
    const input = screen.getByTestId("pf-n-inputs-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.blur(input);
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.blur(input); // busy 中 → 無視
    expect(rewriteMock).toHaveBeenCalledTimes(1);
    resolve({ applied: true, code: NEW_CODE, spec: spec({ n_inputs: 3 }) });
    await waitFor(() => expect(pfParams().code).toBe(NEW_CODE));
  });

  it("IME composition 中の Enter では commit しない", () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({ applied: true, code: NEW_CODE, spec: spec() });
    renderEditor();
    const name0 = screen.getByTestId("pf-in-name-0") as HTMLInputElement;
    fireEvent.compositionStart(name0);
    fireEvent.change(name0, { target: { value: "そくど" } });
    fireEvent.keyDown(name0, { key: "Enter" });
    expect(rewriteMock).not.toHaveBeenCalled();
    fireEvent.compositionEnd(name0);
    fireEvent.keyDown(name0, { key: "Enter" });
    expect(rewriteMock).toHaveBeenCalledTimes(1);
  });
});
