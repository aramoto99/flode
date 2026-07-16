// ADR-0056 §F2: appStore の `lastFailure` / `activeErrorTab` / reducer をテスト。

import { beforeEach, describe, expect, it } from "vitest";

import { useAppStore } from "../src/store/appStore";
import type { FailurePayload, FlwModel, StreamMessage } from "../src/types/api";

const _PAYLOAD: FailurePayload = {
  category: "divide_by_zero",
  template_key: "error.divide_by_zero",
  template_args: { block_label: "Divide1", t: 1.234 },
  block_id: "div_1",
  block_ids: ["div_1"],
  block_type: "flode.blocks.mathops.Divide",
  block_label: "Divide1",
  t: 1.234,
  raw_message: "ZeroDivisionError: float division by zero",
  raw_traceback: "tb",
};

function _reset(): void {
  useAppStore.setState({
    lastFailure: null,
    lastFailureSource: null,
    activeErrorTab: false,
    status: "idle",
    simulationId: null,
  });
}

beforeEach(() => {
  _reset();
});

describe("appStore failure reducers", () => {
  it("setLastFailure with runtime payload populates state + auto-focuses Error tab", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    const s = useAppStore.getState();
    expect(s.lastFailure).toEqual(_PAYLOAD);
    expect(s.lastFailureSource).toBe("runtime");
    expect(s.activeErrorTab).toBe(true);
    expect(s.status).toBe("failed");
  });

  it("setLastFailure(null) clears state", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().setLastFailure(null, "runtime");
    const s = useAppStore.getState();
    expect(s.lastFailure).toBeNull();
    expect(s.activeErrorTab).toBe(false);
  });

  it("startedSimulation clears lastFailure / activeErrorTab", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().startedSimulation("sim_x");
    const s = useAppStore.getState();
    expect(s.lastFailure).toBeNull();
    expect(s.activeErrorTab).toBe(false);
    expect(s.lastFailureSource).toBeNull();
    expect(s.status).toBe("running");
  });

  it("handleStreamMessage with failed+category populates structured failure", () => {
    const msg: StreamMessage = {
      type: "failed",
      duration_sec: 0.5,
      category: _PAYLOAD.category,
      template_key: _PAYLOAD.template_key,
      template_args: _PAYLOAD.template_args,
      block_id: _PAYLOAD.block_id,
      block_ids: _PAYLOAD.block_ids,
      block_type: _PAYLOAD.block_type,
      block_label: _PAYLOAD.block_label,
      t: _PAYLOAD.t,
      raw_message: _PAYLOAD.raw_message,
      raw_traceback: _PAYLOAD.raw_traceback,
    };
    useAppStore.getState().handleStreamMessage(msg);
    const s = useAppStore.getState();
    expect(s.status).toBe("failed");
    expect(s.lastFailure).toEqual(_PAYLOAD);
    expect(s.lastFailureSource).toBe("runtime");
    expect(s.activeErrorTab).toBe(true);
  });

  it("handleStreamMessage with failed but no category just sets status", () => {
    const msg: StreamMessage = { type: "failed", duration_sec: 1.0 };
    useAppStore.getState().handleStreamMessage(msg);
    const s = useAppStore.getState();
    expect(s.status).toBe("failed");
    expect(s.lastFailure).toBeNull();
  });

  it("setActiveErrorTab toggles flag without touching lastFailure", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().setActiveErrorTab(false);
    expect(useAppStore.getState().activeErrorTab).toBe(false);
    expect(useAppStore.getState().lastFailure).toEqual(_PAYLOAD);
  });
});

describe("appStore focusBlock", () => {
  function _setModel(blocks: FlwModel["blocks"]): void {
    useAppStore.setState({
      editingModel: {
        schema_version: "1.0",
        blocks,
        connections: [],
        config: { t_end: 1.0, dt: 0.01, solver: "RK45" },
      } as unknown as FlwModel,
      editingPath: [],
      focusBlockRequest: null,
    });
  }

  it("focuses a top-level block: sets editingPath [], selection, request", () => {
    _setModel([{ id: "g", type: "flode.blocks.mathops.Gain", params: {} }]);
    useAppStore.getState().focusBlock("g");
    const s = useAppStore.getState();
    expect(s.editingPath).toEqual([]);
    expect(s.selectedNodeIds).toEqual(["g"]);
    expect(s.focusBlockRequest?.blockId).toBe("g");
  });

  it("focuses a nested block: drilldown path is set", () => {
    _setModel([
      {
        id: "sub",
        type: "flode.subsystems.Subsystem",
        params: {
          blocks: [{ id: "inner", type: "flode.blocks.sinks.Scope", params: {} }],
        },
      },
    ]);
    useAppStore.getState().focusBlock("inner");
    const s = useAppStore.getState();
    expect(s.editingPath).toEqual(["sub"]);
    expect(s.selectedNodeIds).toEqual(["inner"]);
  });

  it("is a no-op for a block not in the model", () => {
    _setModel([{ id: "g", type: "flode.blocks.mathops.Gain", params: {} }]);
    useAppStore.setState({ selectedNodeIds: [], focusBlockRequest: null });
    useAppStore.getState().focusBlock("missing");
    const s = useAppStore.getState();
    expect(s.focusBlockRequest).toBeNull();
    expect(s.selectedNodeIds).toEqual([]);
  });

  it("increments nonce on repeated focus of the same block", () => {
    _setModel([{ id: "g", type: "flode.blocks.mathops.Gain", params: {} }]);
    useAppStore.getState().focusBlock("g");
    const n1 = useAppStore.getState().focusBlockRequest!.nonce;
    useAppStore.getState().focusBlock("g");
    const n2 = useAppStore.getState().focusBlockRequest!.nonce;
    expect(n2).toBe(n1 + 1);
  });
});
