// SPEC-0025 / ADR-0075: PythonFunctionEditor の PARAMETERS 節構造編集
// (追加 / 削除 / rename)。
// - rename は user_params の key を pruning より前に追随させる (§7 / V15)
// - P1〜P4 のクライアント側検証 (違反はサーバに送らない + draft ロールバック)
// - x0 行 (n_states>0) は名前入力と削除が disabled + hint
// - 追加ボタンの disabled 条件 (空 / 検証違反 / 重複 / 上限 32)

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
  putPythonSpec,
} from "../src/lib/pythonFunctionSpec";
import { useAppStore } from "../src/store/appStore";

const CODE = "@block\ndef f(t: float, u: float, *, k: float = 2.0) -> float:\n    return k * u\n";
const NEW_CODE =
  "@block\ndef f(t: float, u: float, *, gain: float = 2.0) -> float:\n    return gain * u\n";

function paramSpec(name: string, type = "float"): PythonFunctionSpec["params_spec"][number] {
  return {
    name,
    type,
    has_default: true,
    default: 2.0,
  } as PythonFunctionSpec["params_spec"][number];
}

function spec(over: Partial<PythonFunctionSpec> = {}): PythonFunctionSpec {
  return {
    resolved: true,
    func_name: "f",
    n_inputs: 1,
    n_outputs: 1,
    n_states: 0,
    direct_feedthrough: true,
    sample_time: null,
    params_spec: [paramSpec("k")],
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

function model(code: string, userParams: Record<string, unknown>): FlwModel {
  return {
    schema_version: "0.10",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      {
        id: "pf",
        type: "flode.blocks.pythonfunc.PythonFunction",
        params: { code, user_params: userParams },
      },
    ],
    connections: [],
    layout: {},
  } as unknown as FlwModel;
}

function pfParams(): Record<string, unknown> {
  const m = useAppStore.getState().editingModel;
  const b = (m?.blocks ?? []).find((x) => x.id === "pf");
  return (b?.params ?? {}) as Record<string, unknown>;
}

function renderEditor(code = CODE, userParams: Record<string, unknown> = {}) {
  useAppStore.setState({
    editingModel: model(code, userParams),
    editingPath: [],
    selectedNodeId: "pf",
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const block = {
    id: "pf",
    type: "flode.blocks.pythonfunc.PythonFunction",
    params: { code, user_params: userParams },
  };
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

describe("PythonFunctionEditor パラメータ構造編集 (SPEC-0025)", () => {
  it("rename commit → rewrite に op:rename、user_params の key が追随する", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({
      applied: true,
      code: NEW_CODE,
      spec: spec({ params_spec: [paramSpec("gain")] }),
    });
    renderEditor(CODE, { k: 5.5 });
    const name = screen.getByTestId("pf-param-name-k") as HTMLInputElement;
    fireEvent.change(name, { target: { value: "gain" } });
    fireEvent.blur(name);
    await waitFor(() => expect(pfParams().code).toBe(NEW_CODE));
    expect(rewriteMock).toHaveBeenCalledWith(CODE, {
      params: [{ op: "rename", from: "k", to: "gain" }],
    });
    // V15: pruning より前に key を差し替えるので値が残る
    expect(pfParams().user_params).toEqual({ gain: 5.5 });
  });

  it("削除 → rewrite に op:remove、値は pruning で落ちる", async () => {
    putPythonSpec(CODE, spec());
    const removed = "@block\ndef f(t: float, u: float) -> float:\n    return k * u\n";
    rewriteMock.mockResolvedValue({
      applied: true,
      code: removed,
      spec: spec({ params_spec: [] }),
    });
    renderEditor(CODE, { k: 5.5 });
    fireEvent.click(screen.getByTestId("pf-param-remove-k"));
    await waitFor(() => expect(pfParams().code).toBe(removed));
    expect(rewriteMock).toHaveBeenCalledWith(CODE, {
      params: [{ op: "remove", name: "k" }],
    });
    expect(pfParams().user_params).toEqual({});
  });

  it("追加 → rewrite に op:add、成功で追加行がクリアされる", async () => {
    putPythonSpec(CODE, spec());
    const added =
      "@block\ndef f(t: float, u: float, *, k: float = 2.0, q: int = 3) -> float:\n    return k * u\n";
    rewriteMock.mockResolvedValue({
      applied: true,
      code: added,
      spec: spec({ params_spec: [paramSpec("k"), paramSpec("q", "int")] }),
    });
    renderEditor();
    fireEvent.change(screen.getByTestId("pf-param-add-type"), { target: { value: "int" } });
    fireEvent.change(screen.getByTestId("pf-param-add-name"), { target: { value: "q" } });
    fireEvent.change(screen.getByTestId("pf-param-add-default"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("pf-param-add-submit"));
    await waitFor(() => expect(pfParams().code).toBe(added));
    expect(rewriteMock).toHaveBeenCalledWith(CODE, {
      params: [{ op: "add", name: "q", type: "int", default: 3 }],
    });
    expect((screen.getByTestId("pf-param-add-name") as HTMLInputElement).value).toBe("");
  });

  it("P1〜P4 違反の rename はサーバに送らず inline error + ロールバック", async () => {
    putPythonSpec(CODE, spec());
    renderEditor();
    const name = screen.getByTestId("pf-param-name-k") as HTMLInputElement;
    fireEvent.change(name, { target: { value: "1abc" } });
    fireEvent.blur(name);
    await waitFor(() =>
      expect(screen.getByTestId("pf-struct-error").textContent).toContain(
        "params.invalid_identifier",
      ),
    );
    expect(rewriteMock).not.toHaveBeenCalled();
    expect(name.value).toBe("k"); // ロールバック
  });

  it("既存名との重複 rename はクライアント側で弾く", async () => {
    putPythonSpec(CODE, spec({ params_spec: [paramSpec("k"), paramSpec("g")] }));
    renderEditor();
    const name = screen.getByTestId("pf-param-name-k") as HTMLInputElement;
    fireEvent.change(name, { target: { value: "g" } });
    fireEvent.blur(name);
    await waitFor(() =>
      expect(screen.getByTestId("pf-struct-error").textContent).toContain(
        "params.name_conflict",
      ),
    );
    expect(rewriteMock).not.toHaveBeenCalled();
  });

  it("x0 行 (n_states>0) は名前入力と削除が disabled + hint、値は編集可", () => {
    putPythonSpec(CODE, spec({ n_states: 1, params_spec: [paramSpec("x0"), paramSpec("k")] }));
    renderEditor();
    expect((screen.getByTestId("pf-param-name-x0") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("pf-param-remove-x0") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("pf-param-x0-hint")).toBeTruthy();
    // k の行は編集できる
    expect((screen.getByTestId("pf-param-name-k") as HTMLInputElement).disabled).toBe(false);
    // 値入力は x0 も従来どおり
    expect(screen.getByTestId("pf-param-x0")).toBeTruthy();
  });

  it("追加ボタンは 空 / keyword / 重複 で disabled、有効名で enabled", () => {
    putPythonSpec(CODE, spec());
    renderEditor();
    const submit = () => screen.getByTestId("pf-param-add-submit") as HTMLButtonElement;
    const nameInput = screen.getByTestId("pf-param-add-name");
    expect(submit().disabled).toBe(true); // 空
    fireEvent.change(nameInput, { target: { value: "def" } });
    expect(submit().disabled).toBe(true); // hard keyword
    fireEvent.change(nameInput, { target: { value: "k" } });
    expect(submit().disabled).toBe(true); // 既存名と重複
    fireEvent.change(nameInput, { target: { value: "gain" } });
    expect(submit().disabled).toBe(false);
  });

  it("パラメータが 32 個で追加 disabled + 上限 hint", () => {
    const many = Array.from({ length: 32 }, (_, i) => paramSpec(`p${i}`));
    putPythonSpec(CODE, spec({ params_spec: many }));
    renderEditor();
    fireEvent.change(screen.getByTestId("pf-param-add-name"), { target: { value: "extra" } });
    expect((screen.getByTestId("pf-param-add-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("pf-param-limit-hint")).toBeTruthy();
  });

  it("型 select が現在型を表示し、変更で op:retype + user_params 値を変換する", async () => {
    putPythonSpec(CODE, spec());
    const retyped =
      "@block\ndef f(t: float, u: float, *, k: int = 2) -> float:\n    return k * u\n";
    rewriteMock.mockResolvedValue({
      applied: true,
      code: retyped,
      spec: spec({ params_spec: [paramSpec("k", "int")] }),
    });
    renderEditor(CODE, { k: 5.5 });
    const select = screen.getByTestId("pf-param-type-k") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("float");
    fireEvent.change(select, { target: { value: "int" } });
    await waitFor(() => expect(pfParams().code).toBe(retyped));
    expect(rewriteMock).toHaveBeenCalledWith(CODE, {
      params: [{ op: "retype", name: "k", type: "int" }],
    });
    // 変換規則: 5.5 → 5 (切り捨てで引き継ぐ)
    expect(pfParams().user_params).toEqual({ k: 5 });
  });

  it("型変更で変換できない設定値はキーを落とす", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({
      applied: true,
      code: NEW_CODE,
      spec: spec({ params_spec: [paramSpec("k", "bool")] }),
    });
    renderEditor(CODE, { k: 5.5 });
    fireEvent.change(screen.getByTestId("pf-param-type-k"), { target: { value: "bool" } });
    await waitFor(() => expect(pfParams().code).toBe(NEW_CODE));
    expect(pfParams().user_params).toEqual({}); // 数値→bool は暗黙変換しない
  });

  it("x0 行の型は read-only ラベル表示 (select ではない)", () => {
    putPythonSpec(CODE, spec({ n_states: 1, params_spec: [paramSpec("x0"), paramSpec("k")] }));
    renderEditor();
    expect(screen.getByTestId("pf-param-type-x0").tagName).toBe("SPAN");
    expect(screen.getByTestId("pf-param-type-x0").textContent).toBe("float");
    expect((screen.getByTestId("pf-param-type-k") as HTMLSelectElement).tagName).toBe("SELECT");
  });

  it("rename の applied:false (unsupported) はローカライズキー rename_unsupported で表示", async () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({
      applied: false,
      error: { message: "an f-string references `k`", lineno: 3, col: null, kind: "unsupported" },
    });
    renderEditor();
    const name = screen.getByTestId("pf-param-name-k") as HTMLInputElement;
    fireEvent.change(name, { target: { value: "gain" } });
    fireEvent.blur(name);
    await waitFor(() =>
      expect(screen.getByTestId("pf-struct-error").textContent).toContain(
        "params.rename_unsupported",
      ),
    );
    expect(name.value).toBe("k"); // ロールバック
  });

  it("IME composition 中の Enter では rename を commit しない", () => {
    putPythonSpec(CODE, spec());
    rewriteMock.mockResolvedValue({ applied: true, code: NEW_CODE, spec: spec() });
    renderEditor();
    const name = screen.getByTestId("pf-param-name-k") as HTMLInputElement;
    fireEvent.compositionStart(name);
    fireEvent.change(name, { target: { value: "gain" } });
    fireEvent.keyDown(name, { key: "Enter" });
    expect(rewriteMock).not.toHaveBeenCalled();
  });
});
