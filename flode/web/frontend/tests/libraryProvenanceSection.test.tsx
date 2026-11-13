// SPEC-0032 §1.4-3 / §1.4-5: Inspector の由来表示 (各状態) と [差し替え] の導線、
// ブロック上の更新マーカー。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BlockEntry,
  FlwModel,
  LibraryEntryDetail,
  LibraryMetadata,
  LibraryRegistryResponse,
} from "../src/types/api";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, listLibraries: vi.fn(), getLibraryEntry: vi.fn() };
});

import * as client from "../src/api/client";
import { BlockNodeView } from "../src/components/BlockNodeView";
import { DialogHost } from "../src/components/DialogHost";
import { LibraryProvenanceSection } from "../src/components/LibraryProvenanceSection";
import i18n from "../src/i18n";
import {
  _resetDialogServiceForTest,
  dialog,
  getCurrentDialog,
} from "../src/lib/dialogService";
import { useAppStore } from "../src/store/appStore";
import { clearAllToasts, useToastStore } from "../src/store/toastStore";

const api = vi.mocked(client);
const SUBSYSTEM = "flode.subsystems.subsystem.Subsystem";
const INPORT = "flode.subsystems.ports.Inport";
const OUTPORT = "flode.subsystems.ports.Outport";

function body(nIn: number): { type: string; params: Record<string, unknown> } {
  const blocks: BlockEntry[] = [];
  for (let i = 0; i < nIn; i++) blocks.push({ id: `in${i + 1}`, type: INPORT, params: { port_idx: i } });
  blocks.push({ id: "out1", type: OUTPORT, params: { port_idx: 0 } });
  return { type: SUBSYSTEM, params: { blocks, connections: [] } };
}

function userLibrary(
  revision: number | null,
  overrides: Partial<LibraryMetadata> = {},
  containsPython = false,
): LibraryMetadata {
  return {
    ...baseUserLibrary(revision, containsPython),
    ...overrides,
  };
}

function baseUserLibrary(revision: number | null, containsPython: boolean): LibraryMetadata {
  return {
    name: "user",
    uid: "uid-A",
    display_name: "My Blocks",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    version: "1",
    origin: "user",
    writable: true,
    write_disabled_reason: "",
    entries:
      revision === null
        ? []
        : [
            {
              id: "pid",
              display_name: "PID Controller",
              display_name_i18n: {},
              description: "",
              description_i18n: {},
              category_suffix: "",
              kind: "subsystem",
              revision,
              updated_at: null,
              contains_python: containsPython,
              python_block_paths: containsPython ? ["code"] : [],
            },
          ],
  };
}

function registry(libraries: LibraryMetadata[]): LibraryRegistryResponse {
  return {
    libraries,
    load_errors: [],
    schema_version: "libraries.v4",
    supported_locales: ["en", "ja"],
    user_library: { name: "user", enabled: true, exists: true, writable: true, write_disabled_reason: "" },
  };
}

function block(revision: number, extra: Partial<BlockEntry["provenance"]> = {}): BlockEntry {
  return {
    id: "PID",
    ...body(1),
    provenance: { library: "user", library_uid: "uid-A", entry: "pid", revision, ...extra },
  };
}

function modelWith(b: BlockEntry): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-6, atol: 1e-8, dt_base: null },
    blocks: [b],
    connections: [],
    layout: { PID: { x: 0, y: 0 } },
  };
}

let queryClient: QueryClient;

async function renderSection(b: BlockEntry, libraries: LibraryMetadata[]): Promise<void> {
  api.listLibraries.mockResolvedValue(registry(libraries));
  useAppStore.getState().setEditingModel(modelWith(b));
  useAppStore.setState({ editingPath: [], selectedFilePath: "m.flw.json", dirty: false });
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={queryClient}>
      <LibraryProvenanceSection block={b} />
    </QueryClientProvider>,
  );
  // 由来が有効なブロックだけがライブラリ一覧を購読する
  if (screen.queryByTestId("library-provenance-section") !== null) {
    await waitFor(() => expect(api.listLibraries).toHaveBeenCalled());
  }
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  _resetDialogServiceForTest();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  clearAllToasts();
});

describe("LibraryProvenanceSection: states", () => {
  it("renders nothing for a block without provenance", async () => {
    await renderSection({ id: "g", type: "flode.blocks.mathops.Gain", params: { k: 1 } }, [userLibrary(2)]);
    expect(screen.queryByTestId("library-provenance-section")).toBeNull();
    expect(api.listLibraries).not.toHaveBeenCalled();
  });

  it("renders nothing for malformed provenance from a model file", async () => {
    const broken = { ...block(1), provenance: { library: "user" } } as unknown as BlockEntry;
    await renderSection(broken, [userLibrary(2)]);
    expect(screen.queryByTestId("library-provenance-section")).toBeNull();
    expect(api.listLibraries).not.toHaveBeenCalled();
  });

  it("up to date: shows the source line, no replace button", async () => {
    await renderSection(block(2), [userLibrary(2)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").getAttribute("data-status")).toBe("current"),
    );
    expect(screen.getByTestId("library-provenance-source").textContent).toBe(
      "My Blocks / PID Controller (rev 2)",
    );
    expect(screen.getByTestId("library-provenance-status").textContent).toBe("Up to date");
    expect(screen.queryByTestId("library-provenance-replace")).toBeNull();
  });

  it("update available: shows the revisions and the replace button", async () => {
    await renderSection(block(2), [userLibrary(3)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe(
        "Update available (rev 2 → 3)",
      ),
    );
    // 由来行はブロックが持つ版 (rev 2) を出す
    expect(screen.getByTestId("library-provenance-source").textContent).toContain("(rev 2)");
    expect(screen.getByTestId("library-provenance-replace").textContent).toBe("Replace");
  });

  it("newer than the library: says so and still allows replacing", async () => {
    await renderSection(block(5), [userLibrary(3)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").getAttribute("data-status")).toBe("ahead"),
    );
    expect(screen.getByTestId("library-provenance-status").textContent).toContain("Newer than the library");
    expect(screen.getByTestId("library-provenance-replace")).toBeTruthy();
  });

  it("source not found: entry deleted, or the uid belongs to someone else's library", async () => {
    await renderSection(block(1), [userLibrary(null)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe("Source not found"),
    );
    // 見つからないときは由来に書かれた名前をそのまま出す
    expect(screen.getByTestId("library-provenance-source").textContent).toBe("user / pid (rev 1)");
    expect(screen.queryByTestId("library-provenance-replace")).toBeNull();
    cleanup();

    await renderSection(block(1, { library_uid: "uid-THEIRS" }), [userLibrary(9)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe("Source not found"),
    );
    expect(screen.queryByTestId("library-provenance-replace")).toBeNull();
  });

  it("clips long and control-character strings that come from the model file", async () => {
    const nasty = block(1, { library: `evil‮${"x".repeat(300)}`, library_uid: undefined, entry: "a\nb" });
    delete nasty.provenance!.library_uid;
    await renderSection(nasty, []);
    const text = (await screen.findByTestId("library-provenance-source")).textContent ?? "";
    expect(text).not.toContain("‮");
    expect(text).not.toContain("\n");
    expect(text.length).toBeLessThan(120);
  });

  it("follows the library list when it is refetched", async () => {
    await renderSection(block(2), [userLibrary(2)]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe("Up to date"),
    );
    api.listLibraries.mockResolvedValue(registry([userLibrary(3)]));
    await queryClient.invalidateQueries({ queryKey: ["libraries-registry"] });
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe(
        "Update available (rev 2 → 3)",
      ),
    );
  });
});

describe("LibraryProvenanceSection: while the library list is not available", () => {
  it("says 'Checking…' instead of 'Source not found' until the list arrives", async () => {
    let release!: (value: LibraryRegistryResponse) => void;
    api.listLibraries.mockReturnValue(
      new Promise<LibraryRegistryResponse>((resolve) => {
        release = resolve;
      }),
    );
    useAppStore.getState().setEditingModel(modelWith(block(2)));
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={queryClient}>
        <LibraryProvenanceSection block={block(2)} />
      </QueryClientProvider>,
    );
    const status = screen.getByTestId("library-provenance-status");
    expect(status.textContent).toBe("Checking…");
    expect(status.getAttribute("data-status")).toBe("checking");
    expect(screen.queryByTestId("library-provenance-replace")).toBeNull();

    release(registry([userLibrary(3)]));
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe(
        "Update available (rev 2 → 3)",
      ),
    );
  });

  it("says the list cannot be loaded when the request fails", async () => {
    api.listLibraries.mockRejectedValue(new Error("503"));
    useAppStore.getState().setEditingModel(modelWith(block(2)));
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={queryClient}>
        <LibraryProvenanceSection block={block(2)} />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe(
        "Cannot load the library list",
      ),
    );
    expect(screen.getByTestId("library-provenance-status").getAttribute("data-status")).toBe(
      "unavailable",
    );
    expect(screen.queryByTestId("library-provenance-replace")).toBeNull();
  });
});

describe("LibraryProvenanceSection: source label of non-user libraries", () => {
  it("adds the internal name when an imported library calls itself 'My Blocks'", async () => {
    const imported = userLibrary(2, {
      name: "acme-lib",
      uid: "uid-A",
      display_name: "My Blocks",
      origin: "imported",
    });
    await renderSection(block(2), [imported]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-status").textContent).toBe("Up to date"),
    );
    expect(screen.getByTestId("library-provenance-source").textContent).toBe(
      "My Blocks (acme-lib) / PID Controller (rev 2)",
    );
  });

  it("does not repeat the name when display name and internal name are the same", async () => {
    const plain = userLibrary(2, { name: "acme", display_name: "acme", origin: "path" });
    await renderSection(block(2), [plain]);
    await waitFor(() =>
      expect(screen.getByTestId("library-provenance-source").textContent).toBe(
        "acme / PID Controller (rev 2)",
      ),
    );
  });
});

describe("LibraryProvenanceSection: replace", () => {
  const DETAIL: LibraryEntryDetail = {
    id: "pid",
    display_name: "PID Controller",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    category_suffix: "",
    kind: "subsystem",
    revision: 3,
    updated_at: null,
    contains_python: false,
    python_block_paths: [],
    library_uid: "uid-A",
    block: { id: "PID", ...body(2) },
  };

  async function clickReplace(): Promise<void> {
    fireEvent.click(await screen.findByTestId("library-provenance-replace"));
    await screen.findByTestId("library-replace-dialog");
  }

  it("the confirmation names the source and states that inner edits are lost; cancel does nothing", async () => {
    await renderSection(block(2), [userLibrary(3)]);
    await clickReplace();
    const text = screen.getByTestId("library-replace-dialog").textContent ?? "";
    expect(text).toContain("rev 2 → rev 3");
    expect(text).toContain("edits you made inside this block will be lost");
    expect(text).toContain("Ctrl+Z");
    expect(text).toContain("PID Controller");
    // 差し替え元: 表示名 + 内部名 + 種別
    expect(screen.getByTestId("library-replace-source").textContent).toBe("My Blocks(user)");
    expect(screen.getByTestId("library-replace-kind").textContent).toContain("your own library");
    expect(screen.queryByTestId("library-replace-python-warning")).toBeNull();
    // 既定 (初期 focus) はキャンセル。Enter では確定しない
    expect(document.activeElement).toBe(screen.getByTestId("library-replace-cancel"));
    fireEvent.keyDown(window, { key: "Enter" });
    expect(api.getLibraryEntry).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("library-replace-cancel"));
    expect(screen.queryByTestId("library-replace-dialog")).toBeNull();
    expect(api.getLibraryEntry).not.toHaveBeenCalled();
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("shows the internal name and 'imported' for an imported library posing as My Blocks", async () => {
    const imported = userLibrary(3, {
      name: "acme-lib",
      display_name: "My Blocks\u202E",
      origin: "imported",
    });
    await renderSection(block(2), [imported]);
    await clickReplace();
    expect(screen.getByTestId("library-replace-source").textContent).toBe("My Blocks (acme-lib)");
    expect(screen.getByTestId("library-replace-kind").textContent).toContain("Imported library");
  });

  it("warns when the library version contains Python code", async () => {
    await renderSection(block(2), [userLibrary(3, {}, true)]);
    await clickReplace();
    const warning = screen.getByTestId("library-replace-python-warning");
    expect(warning.textContent).toContain("contains Python code");
    expect(warning.textContent).toContain("with your permissions");
  });

  it("replaces on confirm and notifies", async () => {
    api.getLibraryEntry.mockResolvedValue(DETAIL);
    await renderSection(block(2), [userLibrary(3)]);
    await clickReplace();
    fireEvent.click(screen.getByTestId("library-replace-confirm"));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(screen.queryByTestId("library-replace-dialog")).toBeNull();
    expect(useToastStore.getState().toasts[0]?.message).toContain("rev 3");
    const replaced = useAppStore.getState().editingModel!.blocks[0]!;
    expect(replaced.provenance?.revision).toBe(3);
    expect((replaced.params.blocks as BlockEntry[]).filter((b) => b.type === INPORT)).toHaveLength(2);
    expect(useAppStore.getState().history.past).toHaveLength(1);
  });

  it("lists values that were not carried over in the notification", async () => {
    const withMask = block(2);
    withMask.params = { ...withMask.params, mask_values: { Kp: 2, Old: 1 } };
    api.getLibraryEntry.mockResolvedValue(DETAIL);
    await renderSection(withMask, [userLibrary(3)]);
    await clickReplace();
    fireEvent.click(screen.getByTestId("library-replace-confirm"));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.severity).toBe("warning");
    expect(toast.message).toContain("Values not carried over");
    expect(toast.message).toContain("Kp, Old");
  });

  it("explains which port blocks the replacement and leaves the model alone", async () => {
    api.getLibraryEntry.mockResolvedValue({ ...DETAIL, block: { id: "PID", ...body(0) } });
    await renderSection(block(2), [userLibrary(3)]);
    useAppStore.getState().applyEditingModel((m) => ({
      ...m,
      blocks: [...m.blocks, { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1 } }],
      connections: [{ src: "src", src_idx: 0, dst: "PID", dst_idx: 0 }],
    }));
    const before = useAppStore.getState().editingModel;
    await clickReplace();
    fireEvent.click(screen.getByTestId("library-replace-confirm"));
    await waitFor(() => expect(getCurrentDialog()?.kind).toBe("alert"));
    const message = getCurrentDialog()?.message ?? "";
    expect(message).toContain("cannot keep its existing connections");
    expect(message).toContain("Input 0 is connected");
    expect(useAppStore.getState().editingModel).toBe(before);
  });
});

describe("DialogHost: confirm dialogs and the Enter key", () => {
  it("a normal confirm is accepted by Enter, but not by a repeated (held) Enter", async () => {
    render(<DialogHost />);
    let result: boolean | null = null;
    void dialog.confirm("Proceed?").then((v) => {
      result = v;
    });
    await screen.findByText("Proceed?");
    fireEvent.keyDown(window, { key: "Enter", repeat: true });
    await Promise.resolve();
    expect(result).toBeNull();
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(result).toBe(true));
  });

  it("a danger confirm is not accepted by Enter and starts with Cancel focused", async () => {
    render(<DialogHost />);
    let result: boolean | null = null;
    void dialog
      .confirm("Delete it?", { variant: "danger", okLabel: "Delete", cancelLabel: "Keep" })
      .then((v) => {
        result = v;
      });
    await screen.findByText("Delete it?");
    expect(document.activeElement?.textContent).toBe("Keep");
    fireEvent.keyDown(window, { key: "Enter" });
    await Promise.resolve();
    expect(result).toBeNull();
    expect(screen.getByText("Delete it?")).toBeTruthy();
    // 明示的なクリックで確定する
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(result).toBe(true));
  });

  it("Escape still cancels a danger confirm", async () => {
    render(<DialogHost />);
    let result: boolean | null = null;
    void dialog.confirm("Delete it?", { variant: "danger" }).then((v) => {
      result = v;
    });
    await screen.findByText("Delete it?");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(result).toBe(false));
  });
});

describe("BlockNodeView: library update marker", () => {
  function renderNode(libraryUpdateTitle?: string): void {
    render(
      <ReactFlowProvider>
        <BlockNodeView
          id="PID"
          data={{
            blockType: SUBSYSTEM,
            params: { blocks: [], connections: [] },
            nInputs: 1,
            nOutputs: 1,
            shapeWidth: 120,
            shapeHeight: 60,
            connectedInputs: [],
            connectedOutputs: [],
            flipped: false,
            ...(libraryUpdateTitle !== undefined ? { libraryUpdateTitle } : {}),
          }}
          selected={false}
          type="blockNode"
          zIndex={0}
          isConnectable
          positionAbsoluteX={0}
          positionAbsoluteY={0}
          dragging={false}
          draggable
          selectable
          deletable
        />
      </ReactFlowProvider>,
    );
  }

  it("shows a marker with an explanatory label when an update is available", () => {
    renderNode("A newer version is available in the library (rev 1 → 2).");
    const marker = screen.getByTestId("library-update-marker-PID");
    expect(marker.getAttribute("title")).toContain("rev 1 → 2");
    expect(marker.getAttribute("aria-label")).toContain("newer version");
    // 色だけに頼らない: 矢印の図形を持つ
    expect(marker.querySelector("svg path")).not.toBeNull();
  });

  it("shows no marker otherwise", () => {
    renderNode();
    expect(screen.queryByTestId("library-update-marker-PID")).toBeNull();
  });
});
