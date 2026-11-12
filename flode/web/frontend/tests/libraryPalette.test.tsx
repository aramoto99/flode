// SPEC-0032 §1.2 / §1.3 / §1.6 (ADR-0080): パレットのマイブロックセクション、
// 登録ダイアログ (同名確認・422 表示)、取り込み (dry-run → 確認 → 本番)。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  FailurePayload,
  LibraryEntryMetadata,
  LibraryImportReport,
  LibraryMetadata,
  LibraryRegistryResponse,
  UserLibraryEntryResponse,
  UserLibraryStatus,
} from "../src/types/api";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(),
    listLibraries: vi.fn(),
    registerLibraryEntry: vi.fn(),
    updateLibraryEntryMetadata: vi.fn(),
    deleteLibraryEntry: vi.fn(),
    importLibrary: vi.fn(),
    deleteImportedLibrary: vi.fn(),
    reloadLibraries: vi.fn(),
    exportLibrary: vi.fn(),
  };
});

import * as client from "../src/api/client";
import { BlockPalette } from "../src/components/BlockPalette";
import { ImportLibraryDialog, LibraryEntryDialog } from "../src/components/LibraryDialogs";
import i18n from "../src/i18n";
import { _resetDialogServiceForTest } from "../src/lib/dialogService";
import { clearAllToasts, useToastStore } from "../src/store/toastStore";

const api = vi.mocked(client);
const SUBSYSTEM = "flode.subsystems.subsystem.Subsystem";

function entry(overrides: Partial<LibraryEntryMetadata>): LibraryEntryMetadata {
  return {
    id: "pid",
    display_name: "PID",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    category_suffix: "",
    kind: "subsystem",
    revision: 1,
    updated_at: null,
    contains_python: false,
    python_block_paths: [],
    ...overrides,
  };
}

function library(overrides: Partial<LibraryMetadata>): LibraryMetadata {
  return {
    name: "std",
    uid: null,
    display_name: "Standard",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    version: "1",
    origin: "builtin",
    writable: false,
    write_disabled_reason: "library_read_only",
    entries: [],
    ...overrides,
  };
}

const WRITABLE: UserLibraryStatus = {
  name: "user",
  enabled: true,
  exists: true,
  writable: true,
  write_disabled_reason: "",
};

const USER_LIBRARY = library({
  name: "user",
  uid: "uid-1",
  display_name: "My Blocks",
  origin: "user",
  writable: true,
  write_disabled_reason: "",
  entries: [
    entry({ id: "zeta", display_name: "Zeta" }),
    entry({ id: "pid", display_name: "PID", category_suffix: "controllers", revision: 4 }),
    entry({
      id: "friction",
      display_name: "Friction",
      kind: "python_function",
      contains_python: true,
      python_block_paths: [""],
    }),
  ],
});

const STD_LIBRARY = library({
  entries: [
    entry({ id: "lead", display_name: "Lead Filter" }),
    entry({ id: "wrapped", display_name: "Wrapped Code", contains_python: true, python_block_paths: ["f"] }),
  ],
});

const IMPORTED_LIBRARY = library({
  name: "acme",
  display_name: "Acme",
  origin: "imported",
  entries: [entry({ id: "valve", display_name: "Valve" })],
});

function registry(overrides: Partial<LibraryRegistryResponse> = {}): LibraryRegistryResponse {
  return {
    libraries: [STD_LIBRARY, USER_LIBRARY, IMPORTED_LIBRARY],
    load_errors: [],
    schema_version: "libraries.v4",
    supported_locales: ["en", "ja"],
    user_library: WRITABLE,
    ...overrides,
  };
}

function libraryApiError(code: string, args: Record<string, unknown>, status: number): client.ApiError {
  const structured = {
    category: "library",
    template_key: `error.library.${code}`,
    template_args: { message: `raw ${code}`, ...args },
    raw_message: `raw ${code}`,
    block_id: null,
    block_ids: [],
    block_type: null,
    block_label: null,
    t: null,
    raw_traceback: null,
  } satisfies FailurePayload;
  return new client.ApiError(status, `${status} raw ${code}`, structured, structured);
}

let queryClient: QueryClient;

function renderWithProvider(ui: React.ReactNode): void {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

async function renderPalette(data: LibraryRegistryResponse): Promise<void> {
  api.listLibraries.mockResolvedValue(data);
  renderWithProvider(<BlockPalette />);
  await screen.findByText("Gain");
  await waitFor(() => expect(api.listLibraries).toHaveBeenCalled());
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  api.listBlockMetadata.mockResolvedValue({
    schema_version: "blocks.v2",
    blocks: [
      {
        type_path: "flode.blocks.mathops.Gain",
        display_name: "Gain",
        category: "mathops",
        icon: "",
        docstring_summary: "",
        params_spec: [],
        default_n_inputs: 1,
        default_n_outputs: 1,
        port_shapes_in_default: [],
        port_shapes_out_default: [],
        tags: [],
        is_container: false,
        mask_capable: false,
      },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  clearAllToasts();
  _resetDialogServiceForTest();
});

describe("BlockPalette: My Blocks section", () => {
  it("puts My Blocks above the built-in categories and other libraries after them", async () => {
    await renderPalette(registry());
    const myBlocks = await screen.findByTestId("palette-section-my-blocks");
    const gain = screen.getByText("Gain");
    const std = screen.getByTestId("palette-library-header-std");
    const following = Node.DOCUMENT_POSITION_FOLLOWING;
    expect(myBlocks.compareDocumentPosition(gain) & following).toBeTruthy();
    expect(gain.compareDocumentPosition(std) & following).toBeTruthy();
    // マイブロックは「Library · 名前」セクションとしては出ない
    expect(screen.queryByTestId("palette-library-header-user")).toBeNull();
    expect(within(myBlocks).getByText("My Blocks")).toBeTruthy();
  });

  it("groups entries under category sub-headings (uncategorized first)", async () => {
    await renderPalette(registry());
    const myBlocks = await screen.findByTestId("palette-section-my-blocks");
    const direct = within(myBlocks).getByTestId("palette-my-blocks-group-");
    const controllers = within(myBlocks).getByTestId("palette-my-blocks-group-controllers");
    expect(within(direct).getByText("Zeta")).toBeTruthy();
    expect(within(direct).getByText("Friction")).toBeTruthy();
    expect(within(controllers).getByText("controllers")).toBeTruthy();
    expect(within(controllers).getByText("PID")).toBeTruthy();
    expect(
      direct.compareDocumentPosition(controllers) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the PY badge on entries that contain Python, in every library", async () => {
    await renderPalette(registry());
    await screen.findByTestId("palette-section-my-blocks");
    expect(screen.getByTestId("palette-entry-py-user-friction").textContent).toBe("PY");
    expect(screen.getByTestId("palette-entry-py-std-wrapped").textContent).toBe("PY");
    expect(screen.queryByTestId("palette-entry-py-user-pid")).toBeNull();
    expect(screen.queryByTestId("palette-entry-py-std-lead")).toBeNull();
    // 種別バッジ: マイブロックの Subsystem は SUB、他ライブラリは LIB
    expect(within(screen.getByTestId("palette-entry-user-pid")).getByText("SUB")).toBeTruthy();
    expect(within(screen.getByTestId("palette-entry-std-lead")).getByText("LIB")).toBeTruthy();
  });

  it("search filters My Blocks too (by name and by category)", async () => {
    await renderPalette(registry());
    await screen.findByTestId("palette-section-my-blocks");
    const search = screen.getByRole("searchbox");
    fireEvent.change(search, { target: { value: "zet" } });
    expect(screen.getByTestId("palette-entry-user-zeta")).toBeTruthy();
    expect(screen.queryByTestId("palette-entry-user-pid")).toBeNull();
    expect(screen.queryByText("Gain")).toBeNull();

    fireEvent.change(search, { target: { value: "controllers" } });
    expect(screen.getByTestId("palette-entry-user-pid")).toBeTruthy();
    expect(screen.queryByTestId("palette-entry-user-zeta")).toBeNull();

    fireEvent.change(search, { target: { value: "no-such-thing" } });
    expect(screen.queryByTestId("palette-section-my-blocks")).toBeNull();
    expect(screen.getByText("No blocks match.")).toBeTruthy();
  });

  it("shows a one-line hint when the user library is empty or not created yet", async () => {
    await renderPalette(
      registry({
        libraries: [STD_LIBRARY],
        user_library: { ...WRITABLE, exists: false },
      }),
    );
    const empty = await screen.findByTestId("palette-my-blocks-empty");
    expect(empty.textContent).toContain("Add to library");
  });

  it("explains why when the user library is disabled (e.g. non-loopback server)", async () => {
    await renderPalette(
      registry({
        libraries: [STD_LIBRARY],
        user_library: {
          name: "user",
          enabled: false,
          exists: false,
          writable: false,
          write_disabled_reason: "library_write_forbidden",
        },
      }),
    );
    const empty = await screen.findByTestId("palette-my-blocks-empty");
    expect(empty.textContent).toContain("loopback");
  });

  it("shows load errors with path and message", async () => {
    await renderPalette(
      registry({ load_errors: [{ path: "C:/libs/bad.flwlib.json", message: "not valid JSON" }] }),
    );
    fireEvent.click(await screen.findByTestId("palette-load-errors-header"));
    const section = screen.getByTestId("palette-load-errors");
    expect(within(section).getByText("C:/libs/bad.flwlib.json")).toBeTruthy();
    expect(within(section).getByText("not valid JSON")).toBeTruthy();
  });
});

describe("BlockPalette: menus and writable", () => {
  it("offers edit / delete on My Blocks entries only", async () => {
    await renderPalette(registry());
    fireEvent.contextMenu(await screen.findByTestId("palette-entry-user-pid"));
    const edit = screen.getByTestId("palette-menu-edit-entry");
    expect(edit.getAttribute("aria-disabled")).toBe("false");
    expect(screen.getByTestId("palette-menu-delete-entry")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("palette-entry-menu")).toBeNull();

    fireEvent.contextMenu(screen.getByTestId("palette-entry-std-lead"));
    expect(screen.queryByTestId("palette-entry-menu")).toBeNull();
  });

  it("disables write menus with the reason as tooltip when not writable", async () => {
    await renderPalette(
      registry({
        user_library: { ...WRITABLE, writable: false, write_disabled_reason: "user_library_corrupt" },
      }),
    );
    fireEvent.contextMenu(await screen.findByTestId("palette-entry-user-pid"));
    const edit = screen.getByTestId("palette-menu-edit-entry");
    expect(edit.getAttribute("aria-disabled")).toBe("true");
    expect(edit.getAttribute("title")).toContain("damaged");
    fireEvent.click(edit);
    expect(screen.queryByTestId("library-entry-dialog")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });

    // 壊れていても取り込み・再読み込みは使える (再読み込みは復旧手段)
    fireEvent.click(screen.getByTestId("palette-menu-button"));
    expect(screen.getByTestId("palette-menu-import").getAttribute("aria-disabled")).toBe("false");
    expect(screen.getByTestId("palette-menu-reload").getAttribute("aria-disabled")).toBe("false");
  });

  it("disables import and reload on a non-loopback server", async () => {
    await renderPalette(
      registry({
        user_library: {
          ...WRITABLE,
          enabled: false,
          writable: false,
          write_disabled_reason: "library_write_forbidden",
        },
      }),
    );
    fireEvent.click(await screen.findByTestId("palette-menu-button"));
    const importItem = screen.getByTestId("palette-menu-import");
    const reloadItem = screen.getByTestId("palette-menu-reload");
    expect(importItem.getAttribute("aria-disabled")).toBe("true");
    expect(importItem.getAttribute("title")).toContain("loopback");
    expect(reloadItem.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(reloadItem);
    expect(api.reloadLibraries).not.toHaveBeenCalled();
  });

  it("keeps reload enabled when only the user library is disabled", async () => {
    await renderPalette(
      registry({
        libraries: [STD_LIBRARY],
        user_library: {
          name: "user",
          enabled: false,
          exists: false,
          writable: false,
          write_disabled_reason: "user_library_disabled",
        },
      }),
    );
    api.reloadLibraries.mockResolvedValue(registry({ libraries: [STD_LIBRARY] }));
    fireEvent.click(await screen.findByTestId("palette-menu-button"));
    expect(screen.getByTestId("palette-menu-import").getAttribute("aria-disabled")).toBe("true");
    const reloadItem = screen.getByTestId("palette-menu-reload");
    expect(reloadItem.getAttribute("aria-disabled")).toBe("false");
    fireEvent.click(reloadItem);
    await waitFor(() => expect(api.reloadLibraries).toHaveBeenCalledTimes(1));
  });

  it("deletes an entry after confirmation, passing its revision", async () => {
    await renderPalette(registry());
    api.deleteLibraryEntry.mockResolvedValue(undefined);
    fireEvent.contextMenu(await screen.findByTestId("palette-entry-user-pid"));
    fireEvent.click(screen.getByTestId("palette-menu-delete-entry"));
    const { getCurrentDialog, resolveCurrentDialog } = await import("../src/lib/dialogService");
    await waitFor(() => expect(getCurrentDialog()).not.toBeNull());
    expect(getCurrentDialog()?.message).toContain("inline copies");
    resolveCurrentDialog(true);
    await waitFor(() => expect(api.deleteLibraryEntry).toHaveBeenCalledWith("pid", 4));
  });

  it("section menus: export / reload on My Blocks, export / delete on imported libraries", async () => {
    await renderPalette(registry());
    fireEvent.click(await screen.findByTestId("palette-my-blocks-header-menu"));
    expect(screen.getByTestId("palette-menu-export")).toBeTruthy();
    expect(screen.getByTestId("palette-menu-section-reload")).toBeTruthy();
    expect(screen.queryByTestId("palette-menu-delete-library")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });

    fireEvent.contextMenu(screen.getByTestId("palette-library-header-acme"));
    expect(screen.getByTestId("palette-menu-delete-library")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });

    // 組み込み・library_paths のライブラリにはメニューが無い
    expect(screen.queryByTestId("palette-library-header-std-menu")).toBeNull();
  });
});

describe("BlockPalette: import flow", () => {
  const REPORT: LibraryImportReport = {
    dry_run: true,
    library: { name: "acme2", uid: null, display_name: "Acme Two", entry_count: 2 },
    python_entries: [
      { id: "ctrl", display_name: "Controller", python_block_paths: ["inner/code"] },
    ],
    unknown_types: [],
    conflict: null,
  };

  it("runs a dry-run, shows the Python warning, then imports on confirm", async () => {
    await renderPalette(registry());
    api.importLibrary.mockImplementation(async (_content, options) => ({
      ...REPORT,
      dry_run: options.dryRun,
    }));
    const file = new File(['{"name": "acme2"}'], "acme2.flwlib.json", { type: "application/json" });
    // jsdom の File は text() を持たない版があるため補う
    Object.defineProperty(file, "text", { value: async () => '{"name": "acme2"}' });
    fireEvent.change(screen.getByTestId("palette-import-file"), { target: { files: [file] } });

    const dialogEl = await screen.findByTestId("library-import-dialog");
    expect(api.importLibrary).toHaveBeenCalledTimes(1);
    expect(api.importLibrary).toHaveBeenLastCalledWith('{"name": "acme2"}', {
      dryRun: true,
      filename: "acme2.flwlib.json",
    });
    expect(within(dialogEl).getByText("Acme Two")).toBeTruthy();
    const warning = screen.getByTestId("library-import-python-warning");
    expect(warning.textContent).toContain("1 block(s) with Python code");
    expect(warning.textContent).toContain("Only import files from sources you trust");
    expect(screen.getByTestId("library-import-python-ctrl").textContent).toContain("Controller");
    expect(screen.getByTestId("library-import-python-ctrl").textContent).toContain("inner/code");

    fireEvent.click(screen.getByTestId("library-import-confirm"));
    await waitFor(() => expect(api.importLibrary).toHaveBeenCalledTimes(2));
    expect(api.importLibrary).toHaveBeenLastCalledWith('{"name": "acme2"}', {
      dryRun: false,
      filename: "acme2.flwlib.json",
    });
    await waitFor(() => expect(screen.queryByTestId("library-import-dialog")).toBeNull());
    // 成功後に一覧を取り直す
    await waitFor(() => expect(api.listLibraries.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(useToastStore.getState().toasts.at(-1)?.message).toContain("Acme Two");
  });

  it("reports a dry-run failure as a toast without opening the dialog", async () => {
    await renderPalette(registry());
    api.importLibrary.mockRejectedValue(
      libraryApiError("library_file_invalid", { reason: "invalid_json" }, 422),
    );
    const file = new File(["{"], "broken.json");
    Object.defineProperty(file, "text", { value: async () => "{" });
    fireEvent.change(screen.getByTestId("palette-import-file"), { target: { files: [file] } });
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0]?.message).toContain("not valid JSON");
    expect(screen.queryByTestId("library-import-dialog")).toBeNull();
  });
});

describe("ImportLibraryDialog", () => {
  const BASE: LibraryImportReport = {
    dry_run: true,
    library: { name: "acme", uid: null, display_name: "Acme", entry_count: 1 },
    python_entries: [],
    unknown_types: [],
    conflict: null,
  };

  it("blocks confirmation on a name conflict and shows the reason", () => {
    renderWithProvider(
      <ImportLibraryDialog
        filename="a.json"
        content="{}"
        report={{ ...BASE, conflict: { name: "acme", reason: "uid_exists" } }}
        onImported={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId("library-import-conflict").textContent).toContain("same library ID");
    expect((screen.getByTestId("library-import-confirm") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("library-import-python-warning")).toBeNull();
  });

  it("blocks confirmation and lists unknown block types", () => {
    renderWithProvider(
      <ImportLibraryDialog
        filename="a.json"
        content="{}"
        report={{ ...BASE, unknown_types: ["acme.blocks.Foo"] }}
        onImported={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId("library-import-unknown-types").textContent).toContain("acme.blocks.Foo");
    expect((screen.getByTestId("library-import-confirm") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the server error and stays open when the real import fails", async () => {
    api.importLibrary.mockRejectedValue(
      libraryApiError("library_name_conflict", { library: "acme", reason: "exists" }, 409),
    );
    const onImported = vi.fn();
    renderWithProvider(
      <ImportLibraryDialog filename="a.json" content="{}" report={BASE} onImported={onImported} onClose={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("library-import-confirm"));
    const error = await screen.findByTestId("library-import-error");
    expect(error.textContent).toContain("already loaded");
    expect(onImported).not.toHaveBeenCalled();
  });
});

describe("LibraryEntryDialog: registration", () => {
  const BLOCK = {
    id: "PID",
    type: SUBSYSTEM,
    params: { blocks: [], connections: [] },
    provenance: { library: "user", entry: "old", revision: 9 },
  };
  const RESPONSE: UserLibraryEntryResponse = {
    library: "user",
    library_uid: "uid-1",
    entry: entry({ id: "pid", display_name: "PID", revision: 1 }),
  };

  function renderRegister(onDone = vi.fn(), onClose = vi.fn()): { onDone: typeof onDone; onClose: typeof onClose } {
    renderWithProvider(
      <LibraryEntryDialog
        target={{ kind: "register", block: BLOCK }}
        categories={["controllers"]}
        onDone={onDone}
        onClose={onClose}
      />,
    );
    return { onDone, onClose };
  }

  it("defaults the name to the block id and posts {id, type, params} without provenance", async () => {
    api.registerLibraryEntry.mockResolvedValue(RESPONSE);
    const { onDone } = renderRegister();
    const name = screen.getByTestId("library-entry-name") as HTMLInputElement;
    expect(name.value).toBe("PID");
    expect((screen.getByTestId("library-entry-description") as HTMLTextAreaElement).value).toBe("");
    expect((screen.getByTestId("library-entry-category") as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByTestId("library-entry-category"), { target: { value: " controllers " } });
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(RESPONSE));
    expect(api.registerLibraryEntry).toHaveBeenCalledWith({
      block: { id: "PID", type: SUBSYSTEM, params: { blocks: [], connections: [] } },
      display_name: "PID",
      description: "",
      category_suffix: "controllers",
    });
  });

  it("disables submit for a blank or over-long name", () => {
    renderRegister();
    const submit = screen.getByTestId("library-entry-submit") as HTMLButtonElement;
    fireEvent.change(screen.getByTestId("library-entry-name"), { target: { value: "   " } });
    expect(submit.disabled).toBe(true);
    expect(screen.getByTestId("library-entry-name-hint")).toBeTruthy();
    fireEvent.change(screen.getByTestId("library-entry-name"), { target: { value: "x".repeat(65) } });
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("library-entry-name"), { target: { value: "x".repeat(64) } });
    expect(submit.disabled).toBe(false);
    expect(api.registerLibraryEntry).not.toHaveBeenCalled();
  });

  it("on a name conflict asks overwrite / save as new, and Enter (default) saves as new", async () => {
    api.registerLibraryEntry
      .mockRejectedValueOnce(
        libraryApiError("library_entry_name_conflict", { entry_id: "pid", revision: 2, display_name: "PID" }, 409),
      )
      .mockResolvedValueOnce({ ...RESPONSE, entry: entry({ id: "pid_2", display_name: "PID (2)" }) });
    const { onDone } = renderRegister();
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    const conflict = await screen.findByTestId("library-name-conflict-dialog");
    expect(conflict.textContent).toContain('"PID"');
    expect(screen.getByTestId("library-conflict-overwrite").textContent).toContain("rev 2 → 3");
    // 既定 = 別名で保存 (強調ボタン)
    expect(screen.getByTestId("library-conflict-save-as-new").className).toContain("bg-blue-600");
    expect(screen.getByTestId("library-conflict-overwrite").className).not.toContain("bg-blue-600");

    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.registerLibraryEntry).toHaveBeenCalledTimes(2);
    expect(api.registerLibraryEntry.mock.calls[1]?.[0]).toMatchObject({
      display_name: "PID",
      save_as_new: true,
    });
    expect(api.registerLibraryEntry.mock.calls[1]?.[0]).not.toHaveProperty("overwrite_entry_id");
    expect(onDone.mock.calls[0]?.[0].entry.display_name).toBe("PID (2)");
  });

  it("overwrite resends with overwrite_entry_id and expected_revision", async () => {
    api.registerLibraryEntry
      .mockRejectedValueOnce(
        libraryApiError("library_entry_name_conflict", { entry_id: "pid", revision: 2, display_name: "PID" }, 409),
      )
      .mockResolvedValueOnce({ ...RESPONSE, entry: entry({ id: "pid", revision: 3 }) });
    const { onDone } = renderRegister();
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    fireEvent.click(await screen.findByTestId("library-conflict-overwrite"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.registerLibraryEntry.mock.calls[1]?.[0]).toMatchObject({
      overwrite_entry_id: "pid",
      expected_revision: 2,
    });
    expect(api.registerLibraryEntry.mock.calls[1]?.[0]).not.toHaveProperty("save_as_new");
  });

  it("cancelling the conflict dialog returns to the form with the input kept", async () => {
    api.registerLibraryEntry.mockRejectedValueOnce(
      libraryApiError("library_entry_name_conflict", { entry_id: "pid", revision: 2, display_name: "PID" }, 409),
    );
    const { onDone, onClose } = renderRegister();
    fireEvent.change(screen.getByTestId("library-entry-description"), { target: { value: "my note" } });
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    fireEvent.click(await screen.findByTestId("library-conflict-cancel"));
    expect((screen.getByTestId("library-entry-description") as HTMLTextAreaElement).value).toBe("my note");
    expect(onDone).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows why a 422 was rejected (Goto/From path and tag) and stays open", async () => {
    api.registerLibraryEntry.mockRejectedValue(
      libraryApiError(
        "library_entry_invalid",
        {
          reason: "goto_from_not_closed",
          violations: [{ path: "inner/from1", tag: "speed", reason: "unresolved_from" }],
        },
        422,
      ),
    );
    const { onDone } = renderRegister();
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    const error = await screen.findByTestId("library-entry-error");
    expect(error.textContent).toContain("inner/from1");
    expect(error.textContent).toContain("speed");
    expect(onDone).not.toHaveBeenCalled();
    expect((screen.getByTestId("library-entry-name") as HTMLInputElement).value).toBe("PID");
  });

  it("shows unknown type names for a 422 unknown_types", async () => {
    api.registerLibraryEntry.mockRejectedValue(
      libraryApiError("library_entry_invalid", { reason: "unknown_types", unknown_types: ["acme.Foo"] }, 422),
    );
    renderRegister();
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    expect((await screen.findByTestId("library-entry-error")).textContent).toContain("acme.Foo");
  });

  it("tells the user to reload when the file changed on disk", async () => {
    api.registerLibraryEntry.mockRejectedValue(
      libraryApiError("library_changed_on_disk", { path: "C:/x/user.flwlib.json" }, 409),
    );
    renderRegister();
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    expect((await screen.findByTestId("library-entry-error")).textContent).toContain("Reload libraries");
  });
});

describe("LibraryEntryDialog: metadata edit", () => {
  const ENTRY = entry({ id: "pid", display_name: "PID", description: "old", category_suffix: "controllers" });

  it("sends only the changed fields", async () => {
    api.updateLibraryEntryMetadata.mockResolvedValue({ library: "user", library_uid: "uid-1", entry: ENTRY });
    const onDone = vi.fn();
    renderWithProvider(
      <LibraryEntryDialog target={{ kind: "edit", entry: ENTRY }} categories={[]} onDone={onDone} onClose={vi.fn()} />,
    );
    expect((screen.getByTestId("library-entry-name") as HTMLInputElement).value).toBe("PID");
    fireEvent.change(screen.getByTestId("library-entry-description"), { target: { value: "new" } });
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.updateLibraryEntryMetadata).toHaveBeenCalledWith("pid", { description: "new" });
  });

  it("closes without a request when nothing changed", () => {
    const onClose = vi.fn();
    renderWithProvider(
      <LibraryEntryDialog target={{ kind: "edit", entry: ENTRY }} categories={[]} onDone={vi.fn()} onClose={onClose} />,
    );
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    expect(onClose).toHaveBeenCalled();
    expect(api.updateLibraryEntryMetadata).not.toHaveBeenCalled();
  });
});

/** 外から resolve / reject できる Promise (通信中の状態を作るため)。 */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("dialogs while a request is in flight", () => {
  const BLOCK = { id: "PID", type: SUBSYSTEM, params: {} };
  const RESPONSE: UserLibraryEntryResponse = {
    library: "user",
    library_uid: "uid-1",
    entry: entry({ id: "pid" }),
  };

  it("the entry dialog cannot be closed (Cancel / Escape / backdrop) until the request settles", async () => {
    const pending = deferred<UserLibraryEntryResponse>();
    api.registerLibraryEntry.mockReturnValue(pending.promise);
    const onClose = vi.fn();
    const onDone = vi.fn();
    renderWithProvider(
      <LibraryEntryDialog
        target={{ kind: "register", block: BLOCK }}
        categories={[]}
        onDone={onDone}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    const cancel = screen.getByTestId("library-entry-cancel") as HTMLButtonElement;
    await waitFor(() => expect(cancel.disabled).toBe(true));
    fireEvent.click(cancel);
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(onClose).not.toHaveBeenCalled();

    pending.resolve(RESPONSE);
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(RESPONSE));
  });

  it("the import dialog cannot be closed until the import settles", async () => {
    const pending = deferred<LibraryImportReport>();
    api.importLibrary.mockReturnValue(pending.promise);
    const onClose = vi.fn();
    const onImported = vi.fn();
    const report: LibraryImportReport = {
      dry_run: true,
      library: { name: "acme", uid: null, display_name: "Acme", entry_count: 1 },
      python_entries: [],
      unknown_types: [],
      conflict: null,
    };
    renderWithProvider(
      <ImportLibraryDialog
        filename="a.json"
        content="{}"
        report={report}
        onImported={onImported}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("library-import-confirm"));
    const cancel = screen.getByTestId("library-import-cancel") as HTMLButtonElement;
    await waitFor(() => expect(cancel.disabled).toBe(true));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(onClose).not.toHaveBeenCalled();

    pending.resolve({ ...report, dry_run: false });
    await waitFor(() => expect(onImported).toHaveBeenCalled());
  });

  it("a held-down Enter (key repeat) does not confirm the name-conflict dialog", async () => {
    api.registerLibraryEntry.mockRejectedValueOnce(
      libraryApiError("library_entry_name_conflict", { entry_id: "pid", revision: 2, display_name: "PID" }, 409),
    );
    renderWithProvider(
      <LibraryEntryDialog
        target={{ kind: "register", block: BLOCK }}
        categories={[]}
        onDone={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("library-entry-submit"));
    await screen.findByTestId("library-name-conflict-dialog");
    fireEvent.keyDown(window, { key: "Enter", repeat: true });
    fireEvent.keyDown(window, { key: "Enter", repeat: true });
    expect(api.registerLibraryEntry).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("library-name-conflict-dialog")).toBeTruthy();
  });
});

describe("BlockPalette: details", () => {
  it("keeps what was typed in the edit dialog when the library list is refetched", async () => {
    await renderPalette(registry());
    fireEvent.contextMenu(await screen.findByTestId("palette-entry-user-pid"));
    fireEvent.click(screen.getByTestId("palette-menu-edit-entry"));
    const name = (await screen.findByTestId("library-entry-name")) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "PID tuned" } });
    fireEvent.change(screen.getByTestId("library-entry-description"), { target: { value: "draft" } });

    // 別タブでの更新 → フォーカス復帰時の再取得に相当 (同じエントリの名前と revision が変わる)
    const calls = api.listLibraries.mock.calls.length;
    api.listLibraries.mockResolvedValue(
      registry({
        libraries: [
          STD_LIBRARY,
          { ...USER_LIBRARY, entries: [entry({ id: "pid", display_name: "Renamed elsewhere", revision: 5 })] },
        ],
      }),
    );
    await queryClient.invalidateQueries({ queryKey: ["libraries-registry"] });
    await waitFor(() => expect(api.listLibraries.mock.calls.length).toBeGreaterThan(calls));
    await screen.findByText("Renamed elsewhere");

    expect((screen.getByTestId("library-entry-name") as HTMLInputElement).value).toBe("PID tuned");
    expect((screen.getByTestId("library-entry-description") as HTMLTextAreaElement).value).toBe("draft");
  });

  it("rejects an oversized import file without reading it", async () => {
    await renderPalette(registry());
    const file = new File(["{}"], "huge.flwlib.json");
    const text = vi.fn(async () => "{}");
    Object.defineProperty(file, "text", { value: text });
    Object.defineProperty(file, "size", { value: 12 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByTestId("palette-import-file"), { target: { files: [file] } });
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0]?.message).toContain("12 MiB");
    expect(text).not.toHaveBeenCalled();
    expect(api.importLibrary).not.toHaveBeenCalled();
  });

  it("accepts an import file exactly at the size limit", async () => {
    await renderPalette(registry());
    api.importLibrary.mockResolvedValue({
      dry_run: true,
      library: { name: "big", uid: null, display_name: "Big", entry_count: 0 },
      python_entries: [],
      unknown_types: [],
      conflict: null,
    });
    const file = new File(["{}"], "big.flwlib.json");
    Object.defineProperty(file, "text", { value: async () => "{}" });
    Object.defineProperty(file, "size", { value: 12 * 1024 * 1024 });
    fireEvent.change(screen.getByTestId("palette-import-file"), { target: { files: [file] } });
    await screen.findByTestId("library-import-dialog");
  });

  it("the menu button toggles: pressing it again while open closes the menu", async () => {
    await renderPalette(registry());
    const button = await screen.findByTestId("palette-menu-button");
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    expect(screen.getByTestId("palette-menu")).toBeTruthy();
    expect(button.getAttribute("aria-expanded")).toBe("true");
    // 2 回目: mousedown (メニュー外) で閉じ、続く click では開き直さない
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    expect(screen.queryByTestId("palette-menu")).toBeNull();
    // 3 回目でまた開く
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    expect(screen.getByTestId("palette-menu")).toBeTruthy();
  });

  it("downloads the exported library through an anchor attached to the document", async () => {
    await renderPalette(registry());
    api.exportLibrary.mockResolvedValue({ filename: "user-uid1.flwlib.json", text: "{}" });
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    let attachedOnClick: boolean | null = null;
    let downloadName = "";
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        attachedOnClick = document.body.contains(this);
        downloadName = this.download;
      });
    fireEvent.click(await screen.findByTestId("palette-my-blocks-header-menu"));
    fireEvent.click(screen.getByTestId("palette-menu-export"));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(api.exportLibrary).toHaveBeenCalledWith("user");
    expect(attachedOnClick).toBe(true);
    expect(downloadName).toBe("user-uid1.flwlib.json");
    // click の後はアンカーを残さず、URL の解放は遅延する
    expect(document.querySelector("a[download]")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    click.mockRestore();
  });
});
