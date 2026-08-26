// SPEC-0023 / ADR-0073 §論点 4 (S): 承認 digest の保存と start の soft gate フロー。

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import {
  parsePythonUnconfirmed,
  readPythonTrust,
  startWithPythonGate,
  writePythonTrust,
} from "../src/lib/pythonTrust";
import { makePythonTrustKey } from "../src/lib/storageKeys";

const DIGEST = "a".repeat(64);

function unconfirmed(digest = DIGEST): ApiError {
  return new ApiError(409, "409 unconfirmed", {
    category: "python_function_unconfirmed",
    template_key: "error.python_function_unconfirmed",
    template_args: { block_labels: ["pf", "sub/pf2"], digest },
    block_id: "pf",
    block_ids: ["pf"],
    block_type: null,
    block_label: "pf",
    t: null,
    raw_message: "confirm",
    raw_traceback: null,
  }, null);
}

beforeEach(() => {
  localStorage.clear();
});

describe("trust storage", () => {
  it("round-trips via localStorage with the storageKeys convention", () => {
    expect(readPythonTrust("ws", "a/b.flw.json")).toBeNull();
    writePythonTrust("ws", "a/b.flw.json", DIGEST);
    expect(readPythonTrust("ws", "a/b.flw.json")).toBe(DIGEST);
    expect(localStorage.getItem(makePythonTrustKey("ws", "a/b.flw.json"))).toBe(DIGEST);
    // 別ワークスペース / 別モデルには伝播しない
    expect(readPythonTrust("other", "a/b.flw.json")).toBeNull();
    expect(readPythonTrust("ws", "c.flw.json")).toBeNull();
  });
});

describe("parsePythonUnconfirmed", () => {
  it("extracts digest and labels from the 409 detail", () => {
    expect(parsePythonUnconfirmed(unconfirmed())).toEqual({
      digest: DIGEST,
      blockLabels: ["pf", "sub/pf2"],
    });
  });

  it("returns null for other errors", () => {
    expect(parsePythonUnconfirmed(new Error("x"))).toBeNull();
    expect(parsePythonUnconfirmed(new ApiError(409, "other", null, null))).toBeNull();
    expect(
      parsePythonUnconfirmed(
        new ApiError(400, "x", { ...unconfirmed().structured!, category: "start_validation" }, null),
      ),
    ).toBeNull();
  });
});

describe("startWithPythonGate", () => {
  it("starts directly for models without Python blocks", async () => {
    const start = vi.fn().mockResolvedValue({ simulation_id: "s1" });
    const confirm = vi.fn();
    const r = await startWithPythonGate(start, { workspaceHash: "ws", modelPath: "m", confirm });
    expect(r).toEqual({ simulation_id: "s1" });
    expect(start).toHaveBeenCalledWith(undefined);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks once, stores the digest and retries with ack", async () => {
    const start = vi
      .fn()
      .mockRejectedValueOnce(unconfirmed())
      .mockResolvedValueOnce({ simulation_id: "s2" });
    const confirm = vi.fn().mockResolvedValue(true);
    const r = await startWithPythonGate(start, { workspaceHash: "ws", modelPath: "m", confirm });
    expect(r).toEqual({ simulation_id: "s2" });
    expect(confirm).toHaveBeenCalledWith({ digest: DIGEST, blockLabels: ["pf", "sub/pf2"] });
    expect(start).toHaveBeenNthCalledWith(1, undefined);
    expect(start).toHaveBeenNthCalledWith(2, DIGEST);
    expect(readPythonTrust("ws", "m")).toBe(DIGEST);

    // 2 回目以降は保存済 digest を最初から送り、確認しない
    const start2 = vi.fn().mockResolvedValue({ simulation_id: "s3" });
    await startWithPythonGate(start2, { workspaceHash: "ws", modelPath: "m", confirm });
    expect(start2).toHaveBeenCalledWith(DIGEST);
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("returns null (cancel) when the user declines and stores nothing", async () => {
    const start = vi.fn().mockRejectedValue(unconfirmed());
    const confirm = vi.fn().mockResolvedValue(false);
    const r = await startWithPythonGate(start, { workspaceHash: "ws", modelPath: "m", confirm });
    expect(r).toBeNull();
    expect(start).toHaveBeenCalledTimes(1);
    expect(readPythonTrust("ws", "m")).toBeNull();
  });

  it("re-asks when the stored digest is stale (code changed)", async () => {
    writePythonTrust("ws", "m", "old".padEnd(64, "0"));
    const fresh = "b".repeat(64);
    const start = vi
      .fn()
      .mockRejectedValueOnce(unconfirmed(fresh))
      .mockResolvedValueOnce({ simulation_id: "s4" });
    const confirm = vi.fn().mockResolvedValue(true);
    await startWithPythonGate(start, { workspaceHash: "ws", modelPath: "m", confirm });
    expect(start).toHaveBeenNthCalledWith(1, "old".padEnd(64, "0"));
    expect(start).toHaveBeenNthCalledWith(2, fresh);
    expect(readPythonTrust("ws", "m")).toBe(fresh);
  });

  it("propagates unrelated errors untouched", async () => {
    const boom = new ApiError(500, "boom", null, null);
    const start = vi.fn().mockRejectedValue(boom);
    await expect(
      startWithPythonGate(start, { workspaceHash: "ws", modelPath: "m", confirm: vi.fn() }),
    ).rejects.toBe(boom);
  });
});
