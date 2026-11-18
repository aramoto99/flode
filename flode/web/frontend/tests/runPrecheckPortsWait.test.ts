// bug-report 2026-11-19-run-precheck-unresolved-dynamic-ports (レビュー対応):
// 実行前チェックの前に、ポートが引数で変わるユーザーブロックのポートの解決を待つ。
// - 待っている間 (応答前) の判定は「分からない」= 超過と断定しない
// - 解決後に本当に少なければ実行前チェックで止まる (整形メッセージ)
// - 通信失敗・タイムアウト (PRECHECK_PORTS_WAIT_MS) なら待つのをやめ、判定は飛ばす (backend に任せる)
// - params が無いブロック (JSON で省略) も、収集側と判定側でキャッシュのキーが一致する

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockMetadata, FlwModel, ResolvedPortShapes } from "../src/types/api";

const resolveMock =
  vi.fn<(typePath: string, params: Record<string, unknown>) => Promise<ResolvedPortShapes>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    resolvePortShapes: (typePath: string, params: Record<string, unknown>) =>
      resolveMock(typePath, params),
  };
});

import {
  awaitUserBlockPortsForRun,
  precheckRun,
  PRECHECK_PORTS_WAIT_MS,
} from "../src/lib/modelForBackend";
import { queryClient } from "../src/lib/queryClient";
import { BLOCKS_REGISTRY_QUERY_KEY } from "../src/lib/queryKeys";
import {
  _resetUserBlockPortsForTest,
  ensureUserBlockPorts,
  knownUserBlockPorts,
  userBlockPortsKey,
} from "../src/lib/userBlockPorts";

const DYN_TYPE = "flode_ws.io.Split";

const DYN_META: BlockMetadata = {
  type_path: DYN_TYPE,
  display_name: "Split",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 0,
  default_n_outputs: 1,
  port_shapes_in_default: [],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
  input_names: [],
  output_names: [],
  dynamic_ports: true,
};
const CONST_META: BlockMetadata = {
  ...DYN_META,
  type_path: "flode.blocks.sources.Constant",
  display_name: "Constant",
  source: "builtin",
  dynamic_ports: undefined,
};

/** 2 本の入力が必要な引数 (既定の 0 本では in[0] / in[1] が超過に見える)。 */
const TWO_INPUTS: ResolvedPortShapes = {
  n_inputs: 2,
  n_outputs: 1,
  port_shapes_in: [[], []],
  port_shapes_out: [[]],
  input_names: [],
  output_names: [],
};
const ONE_INPUT: ResolvedPortShapes = { ...TWO_INPUTS, n_inputs: 1, port_shapes_in: [[]] };

function model(params: Record<string, unknown> | undefined): FlwModel {
  const bin = { id: "bin", type: DYN_TYPE, params } as FlwModel["blocks"][number];
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [{ id: "c", type: CONST_META.type_path, params: {} }, bin],
    connections: [
      { src: "c", src_idx: 0, dst: "bin", dst_idx: 0 },
      { src: "c", src_idx: 0, dst: "bin", dst_idx: 1 },
    ],
  };
}

/** 後で解決・失敗させられる応答。 */
function deferred(): {
  promise: Promise<ResolvedPortShapes>;
  resolve: (v: ResolvedPortShapes) => void;
  reject: (e: unknown) => void;
} {
  let resolve!: (v: ResolvedPortShapes) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<ResolvedPortShapes>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  _resetUserBlockPortsForTest();
  resolveMock.mockReset();
  queryClient.setQueryData(BLOCKS_REGISTRY_QUERY_KEY, { blocks: [DYN_META, CONST_META] });
});

afterEach(() => {
  vi.useRealTimers();
  queryClient.removeQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
});

describe("the run waits for the dynamic ports before the precheck", () => {
  it("is undecided while the request is pending, then stops a really-excess model", async () => {
    const pending = deferred();
    resolveMock.mockReturnValue(pending.promise);
    const m = model({ parts: 1 });

    const waiting = awaitUserBlockPortsForRun(m);
    // 応答前の判定は「分からない」(超過と断定しない)
    expect(precheckRun(m)).toBeNull();

    pending.resolve(ONE_INPUT);
    await waiting;
    const failure = precheckRun(m);
    expect(failure?.category).toBe("excess_port_connections");
    expect(failure?.template_args.ports).toEqual(["bin.in[1]"]);
  });

  it("lets a valid model through once resolved", async () => {
    resolveMock.mockResolvedValue(TWO_INPUTS);
    const m = model({ parts: 2 });
    await awaitUserBlockPortsForRun(m);
    expect(precheckRun(m)).toBeNull();
  });

  it("joins the request already in flight (no extra request)", async () => {
    const pending = deferred();
    resolveMock.mockReturnValue(pending.promise);
    const m = model({ parts: 2 });
    const opened = ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { parts: 2 } }]);
    const waiting = awaitUserBlockPortsForRun(m);
    pending.resolve(TWO_INPUTS);
    await Promise.all([opened, waiting]);
    expect(resolveMock).toHaveBeenCalledTimes(1);
  });

  it("gives up after a network failure and leaves the check to the backend", async () => {
    resolveMock.mockRejectedValue(new TypeError("network"));
    const m = model({ parts: 1 });
    await awaitUserBlockPortsForRun(m);
    expect(precheckRun(m)).toBeNull();
  });

  it("gives up after PRECHECK_PORTS_WAIT_MS when the server does not answer", async () => {
    vi.useFakeTimers();
    resolveMock.mockReturnValue(new Promise<ResolvedPortShapes>(() => {}));
    const m = model({ parts: 1 });
    let done = false;
    const waiting = awaitUserBlockPortsForRun(m).then(() => {
      done = true;
    });
    await vi.advanceTimersByTimeAsync(PRECHECK_PORTS_WAIT_MS - 1);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await waiting;
    expect(done).toBe(true);
    expect(precheckRun(m)).toBeNull();
  });
});

describe("blocks without params (omitted in the JSON)", () => {
  it("use the same cache key on the collecting and the checking side", async () => {
    expect(userBlockPortsKey(DYN_TYPE, undefined)).toBe(userBlockPortsKey(DYN_TYPE, {}));
    resolveMock.mockResolvedValue(ONE_INPUT);
    const m = model(undefined);
    await awaitUserBlockPortsForRun(m);
    expect(resolveMock).toHaveBeenCalledWith(DYN_TYPE, {});
    expect(knownUserBlockPorts(DYN_META, undefined)?.nInputs).toBe(1);
    expect(precheckRun(m)?.template_args.ports).toEqual(["bin.in[1]"]);
  });
});
