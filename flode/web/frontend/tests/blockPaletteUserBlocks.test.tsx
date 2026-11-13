// ADR-0081 §8 (U4): パレットのユーザーブロックのセクション・読み込みエラー欄・再読み込み。
//
// カバレッジ:
//   * セクションの並び (ワークスペース → dirs → modules、組み込みより上)・サブ見出し・件数
//   * 読み込み元はあるがブロック 0 件 → 1 行の説明 / 未設定 → セクションも最下部の欄も出さない
//   * user_blocks.enabled=false → 理由を 1 行 / reload_allowed=false → 再読み込みを無効化
//   * CATEGORY_ORDER 外の組み込みカテゴリが消えない
//   * 読み込みエラー欄 (件数・info・整形)・読んだファイルの一覧
//   * 再読み込み: 成功で invalidate + トースト、409 等のエラー文言、二重実行防止
//   * 検索 (型名・説明・読み込み元名)

import i18n from "../src/i18n"; // i18next 初期化 (en 文言で assert する)

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, listBlockMetadata, reloadBlocks } from "../src/api/client";
import { BlockPalette } from "../src/components/BlockPalette";
import { clearAllToasts, useToastStore } from "../src/store/toastStore";
import type {
  BlockMetadata,
  BlockRegistryResponse,
  BlockReloadResponse,
} from "../src/types/api";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(),
    listLibraries: vi.fn(async () => ({
      libraries: [],
      load_errors: [],
      schema_version: "libraries.v1",
      supported_locales: ["en", "ja"],
    })),
    reloadBlocks: vi.fn(),
  };
});

const RLO = String.fromCharCode(0x202e);

function meta(over: Partial<BlockMetadata> & { type_path: string }): BlockMetadata {
  return {
    display_name: over.type_path.split(".").at(-1) ?? over.type_path,
    category: "",
    icon: "default",
    docstring_summary: "",
    params_spec: [],
    default_n_inputs: 1,
    default_n_outputs: 1,
    port_shapes_in_default: [[]],
    port_shapes_out_default: [[]],
    tags: [],
    is_container: false,
    mask_capable: false,
    source: "builtin",
    ...over,
  };
}

function registry(over: Partial<BlockRegistryResponse> = {}): BlockRegistryResponse {
  return {
    schema_version: "blocks.v3",
    supported_locales: ["en", "ja"],
    blocks: [
      meta({ type_path: "flode.blocks.mathops.Gain", category: "mathops" }),
      meta({ type_path: "flode.blocks.extra.Odd", category: "brand_new_category" }),
      meta({
        type_path: "flode_ws.filters.MovingAverage",
        source: "workspace",
        display_name: "Moving average",
        category: "filters",
        docstring_summary: "Average of the last n samples.",
      }),
      meta({ type_path: "flode_ws.misc.Plain", source: "workspace", display_name: "Plain" }),
      meta({ type_path: "mypkg.blocks.Sender", source: "module:mypkg.blocks" }),
    ],
    sources: [
      {
        id: "module:mypkg.blocks",
        kind: "module",
        label: "mypkg.blocks",
        root: null,
        reloadable: false,
        from_cwd: false,
        files: [],
      },
      {
        id: "workspace",
        kind: "workspace",
        label: "blocks/",
        root: "/home/me/ws/blocks",
        reloadable: true,
        from_cwd: true,
        files: [
          { path: "filters.py", status: "ok" },
          { path: "broken.py", status: "error" },
        ],
      },
      {
        id: "dir:lab",
        kind: "dir",
        label: "lab",
        root: "/home/me/lab",
        reloadable: true,
        from_cwd: false,
        files: [],
      },
    ],
    load_errors: [
      {
        source: "workspace",
        path: "blocks/broken.py",
        line: 3,
        kind: "syntax",
        message: `invalid syntax${RLO}\nnext line`,
        severity: "error",
        type_path: null,
      },
      {
        source: "workspace",
        path: "blocks/__init__.py",
        line: null,
        kind: "spec",
        message: "the top-level __init__.py is not executed",
        severity: "info",
        type_path: null,
      },
    ],
    user_blocks: {
      enabled: true,
      reason: null,
      reload_allowed: true,
      reload_reason: null,
      restart_required_sources: ["module:mypkg.blocks"],
    },
    ...over,
  };
}

function reloadResponse(over: Partial<BlockReloadResponse> = {}): BlockReloadResponse {
  return {
    ...registry(),
    added: ["flode_ws.a.New"],
    removed: [],
    changed: ["flode_ws.filters.MovingAverage", "flode_ws.misc.Plain"],
    restart_required_sources: ["module:mypkg.blocks"],
    errors: registry().load_errors ?? [],
    ...over,
  };
}

let queryClient: QueryClient;

function renderPalette(): ReturnType<typeof render> {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BlockPalette />
    </QueryClientProvider>,
  );
}

async function sectionHeaders(): Promise<string[]> {
  await screen.findAllByTestId("palette-user-section");
  return screen
    .getAllByTestId("palette-user-section")
    .map((el) => el.getAttribute("data-source-id") ?? "");
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  clearAllToasts();
  vi.mocked(listBlockMetadata).mockReset();
  vi.mocked(reloadBlocks).mockReset();
});

afterEach(() => cleanup());

describe("BlockPalette: user block sections", () => {
  it("orders sections workspace -> dirs -> modules above the builtin categories", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    const { container } = renderPalette();
    expect(await sectionHeaders()).toEqual(["workspace", "dir:lab", "module:mypkg.blocks"]);

    const headers = Array.from(
      container.querySelectorAll("button[aria-expanded]"),
    ).map((b) => b.textContent ?? "");
    // 先頭がワークスペース (i18n 文言) + 件数、その後 dirs / modules、組み込みが続く
    expect(headers[0]).toBe("▾Workspace2");
    expect(headers[1]).toBe("▾lab0");
    expect(headers[2]).toBe("▾mypkg.blocks1");
    expect(headers.indexOf("▾Math1")).toBeGreaterThan(2);
  });

  it("shows declared categories as sub-headings and undeclared blocks directly", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    const ws = screen.getAllByTestId("palette-user-section")[0]!;
    const sub = within(ws).getAllByTestId("palette-user-subgroup");
    expect(sub).toHaveLength(1);
    expect(sub[0]!.textContent).toContain("filters");
    expect(within(sub[0]!).getByText("Moving average")).toBeTruthy();
    // 未宣言のブロックはサブ見出しの外 (セクション直下)
    const plain = within(ws).getByText("Plain");
    expect(sub[0]!.contains(plain)).toBe(false);
    // 控えめな印と、読み込み元・型名入りのツールチップ
    const tile = plain.closest("[data-testid='palette-block-tile']")!;
    expect(tile.textContent).toContain("PY");
    expect(tile.getAttribute("title")).toContain("flode_ws.misc.Plain");
    expect(tile.getAttribute("title")).toContain("From: Workspace");
  });

  it("explains an empty source and lists read files in the header tooltip", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    const lab = screen.getAllByTestId("palette-user-section")[1]!;
    expect(within(lab).getByTestId("palette-user-section-empty")).toBeTruthy();
    const wsHeader = screen.getAllByTestId("palette-user-section-header")[0]!;
    const title = wsHeader.getAttribute("title") ?? "";
    expect(title).toContain("Folder: /home/me/ws/blocks");
    expect(title).toContain("filters.py");
    expect(title).toContain("broken.py (error)");
    expect(title).toContain("started in");
  });

  it("does not show user sections or the load panel when nothing is configured", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(
      registry({
        blocks: [meta({ type_path: "flode.blocks.mathops.Gain", category: "mathops" })],
        sources: [],
        load_errors: [],
        user_blocks: {
          enabled: true,
          reason: null,
          reload_allowed: true,
          reload_reason: null,
          restart_required_sources: [],
        },
      }),
    );
    renderPalette();
    await screen.findByText("Gain");
    expect(screen.queryByTestId("palette-user-section")).toBeNull();
    expect(screen.queryByTestId("palette-load-panel")).toBeNull();
    // ⋯ メニューの「再読み込み」は残る (blocks/ を後から作った場合の入口)
    expect(screen.getByTestId("palette-menu-button")).toBeTruthy();
  });

  it("keeps builtin categories that are not in CATEGORY_ORDER", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    expect(screen.getByText("brand_new_category")).toBeTruthy();
    expect(screen.getByText("Odd")).toBeTruthy();
  });

  it("shows the reason in one line when user blocks are disabled", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(
      registry({
        blocks: [meta({ type_path: "flode.blocks.mathops.Gain", category: "mathops" })],
        sources: [],
        load_errors: [],
        user_blocks: {
          enabled: false,
          reason: `bound to a non-loopback address${RLO}`,
          reload_allowed: false,
          reload_reason: "not enabled",
          restart_required_sources: [],
        },
      }),
    );
    renderPalette();
    const line = await screen.findByTestId("palette-user-blocks-disabled");
    expect(line.textContent).toBe(
      "Python blocks are not loaded: bound to a non-loopback address",
    );
    expect(screen.queryByTestId("palette-reload-button")).toBeNull();
  });

  it("searches user blocks by type path, description and source label", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    const input = screen.getByLabelText("Search blocks…");
    fireEvent.change(input, { target: { value: "last n samples" } });
    expect(screen.getByText("Moving average")).toBeTruthy();
    expect(screen.queryByText("Plain")).toBeNull();
    fireEvent.change(input, { target: { value: "flode_ws.misc" } });
    expect(screen.getByText("Plain")).toBeTruthy();
    fireEvent.change(input, { target: { value: "mypkg.blocks" } });
    expect(screen.getByText("Sender")).toBeTruthy();
    // ヒットの無い読み込み元のセクションは検索中は出さない
    expect(await sectionHeaders()).toEqual(["module:mypkg.blocks"]);
  });

  it("does not crash searching malformed blocks (null category, missing tags)", async () => {
    const broken = {
      ...meta({ type_path: "flode_ws.bad.Weird", source: "workspace" }),
      category: null,
      tags: undefined,
    } as unknown as BlockMetadata;
    vi.mocked(listBlockMetadata).mockResolvedValue(
      registry({ blocks: [...registry().blocks, broken] }),
    );
    renderPalette();
    await sectionHeaders();
    fireEvent.change(screen.getByLabelText("Search blocks…"), { target: { value: "w" } });
    expect(screen.getByText("Weird")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search blocks…"), { target: { value: "zzz" } });
    expect(screen.getByText("No blocks match.")).toBeTruthy();
  });

  it("shows user categories in their original case", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    const label = within(screen.getAllByTestId("palette-user-subgroup")[0]!).getByText(
      "filters",
    );
    expect(label.className).not.toContain("uppercase");
  });

  it("toggles the ⋯ menu closed when the button is pressed again", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    const button = await screen.findByTestId("palette-menu-button");
    // 実際のブラウザと同じく pointerdown → click の順で押す
    fireEvent.pointerDown(button);
    fireEvent.click(button);
    expect(screen.getByTestId("palette-menu")).toBeTruthy();
    fireEvent.pointerDown(button);
    fireEvent.click(button);
    expect(screen.queryByTestId("palette-menu")).toBeNull();
    // 外側の pointerdown / Escape でも閉じる
    fireEvent.click(button);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId("palette-menu")).toBeNull();
    fireEvent.click(button);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("palette-menu")).toBeNull();
  });

  it("moves the right-click menu to the new position on another right-click", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    await sectionHeaders();
    const headers = screen.getAllByTestId("palette-user-section-header");
    fireEvent.contextMenu(headers[0]!, { clientX: 10, clientY: 20 });
    expect(screen.getByTestId("palette-menu").style.top).toBe("20px");
    fireEvent.pointerDown(headers[1]!);
    expect(screen.queryByTestId("palette-menu")).toBeNull();
    fireEvent.contextMenu(headers[1]!, { clientX: 10, clientY: 60 });
    expect(screen.getByTestId("palette-menu").style.top).toBe("60px");
  });
});

describe("BlockPalette: load errors panel", () => {
  it("is closed by default, counts errors only, and cleans messages", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    renderPalette();
    const details = (await screen.findByTestId("palette-load-errors")) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")!.textContent).toBe("Load errors (1)");
    const rows = within(details).getAllByTestId("palette-load-error-row");
    expect(rows.map((r) => r.getAttribute("data-severity"))).toEqual(["error", "info"]);
    expect(rows[0]!.textContent).toContain("Workspace");
    expect(rows[0]!.textContent).toContain("blocks/broken.py:3");
    expect(rows[0]!.textContent).toContain("Syntax error");
    expect(rows[0]!.textContent).toContain("invalid syntax next line");
    expect(rows[0]!.textContent).not.toContain(RLO);
    expect(rows[1]!.textContent).toContain("Note");
    const files = within(details).getByTestId("palette-load-files");
    expect(files.textContent).toContain("broken.py");
    expect(files.textContent).toContain("lab");
  });

  it("disables reload with the server reason as a tooltip when not allowed", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(
      registry({
        user_blocks: {
          enabled: true,
          reason: null,
          reload_allowed: false,
          reload_reason: "blocks are read only at startup",
          restart_required_sources: [],
        },
      }),
    );
    renderPalette();
    const button = (await screen.findByTestId("palette-reload-button")) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toBe("blocks are read only at startup");
    fireEvent.click(screen.getByTestId("palette-menu-button"));
    const item = screen.getByTestId("palette-menu-reload") as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    expect(item.title).toBe("blocks are read only at startup");
  });
});

describe("BlockPalette: reload", () => {
  it("invalidates the registry and shows counts, errors and the restart note", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    vi.mocked(reloadBlocks).mockResolvedValue(reloadResponse());
    renderPalette();
    const button = await screen.findByTestId("palette-reload-button");
    const calls = vi.mocked(listBlockMetadata).mock.calls.length;
    fireEvent.click(button);
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(vi.mocked(listBlockMetadata).mock.calls.length).toBeGreaterThan(calls);
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.severity).toBe("warning");
    expect(toast.message).toContain("1 added, 0 removed, 2 changed");
    expect(toast.message).toContain("1 load error(s)");
    expect(toast.message).toContain("Changes to installed packages (mypkg.blocks)");
  });

  it("does not send a second request while one is pending", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    let resolve: (v: BlockReloadResponse) => void = () => undefined;
    vi.mocked(reloadBlocks).mockImplementation(
      () => new Promise<BlockReloadResponse>((r) => (resolve = r)),
    );
    renderPalette();
    const button = (await screen.findByTestId("palette-reload-button")) as HTMLButtonElement;
    fireEvent.click(button);
    fireEvent.click(button);
    // メニューからの実行も同じ状態を見る
    fireEvent.click(screen.getByTestId("palette-menu-button"));
    fireEvent.click(screen.getByTestId("palette-menu-reload"));
    expect(vi.mocked(reloadBlocks)).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(button.disabled).toBe(true));
    await act(async () => {
      resolve(reloadResponse({ errors: [], restart_required_sources: [] }));
    });
    await waitFor(() => expect(button.disabled).toBe(false));
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.severity).toBe("success");
  });

  it.each([
    [409, "reload_in_progress", "Blocks are already being reloaded"],
    [403, "reload_not_allowed", "Reloading blocks is not allowed on this server (nope)."],
    [403, "user_blocks_disabled", "Python blocks are not enabled on this server (nope)."],
    [400, "invalid_reload_body", "The server rejected the reload request (nope)."],
  ])("shows the %s %s error text", async (status, code, expected) => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    vi.mocked(reloadBlocks).mockRejectedValue(
      new ApiError(
        status,
        `${status} nope`,
        {
          category: "user_blocks",
          template_key: `error.user_blocks.${code}`,
          template_args: { message: "nope" },
          block_id: null,
          block_ids: [],
          block_type: null,
          block_label: null,
          t: null,
          raw_message: "nope",
          raw_traceback: null,
        },
        null,
      ),
    );
    renderPalette();
    fireEvent.click(await screen.findByTestId("palette-reload-button"));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.severity).toBe("error");
    expect(toast.message).toContain(expected);
  });

  it("treats a successful response with missing lists as success", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    vi.mocked(reloadBlocks).mockResolvedValue({
      ...registry(),
    } as unknown as BlockReloadResponse);
    renderPalette();
    fireEvent.click(await screen.findByTestId("palette-reload-button"));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.severity).toBe("success");
    expect(toast.message).toBe("Blocks reloaded: 0 added, 0 removed, 0 changed.");
  });

  it("puts the reload response into the registry cache right away", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    const next = reloadResponse({
      blocks: [
        ...registry().blocks,
        meta({ type_path: "flode_ws.misc.Fresh", source: "workspace", display_name: "Fresh" }),
      ],
    });
    vi.mocked(reloadBlocks).mockResolvedValue(next);
    renderPalette();
    const button = await screen.findByTestId("palette-reload-button");
    // 再取得は旧い registry を返し続ける (= 表示に出るのは setQueryData の結果)
    vi.mocked(listBlockMetadata).mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(button);
    expect(await screen.findByText("Fresh")).toBeTruthy();
  });

  it("shows a generic message for a 500 without a structured detail", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    vi.mocked(reloadBlocks).mockRejectedValue(
      new ApiError(500, "500 Internal Server Error", null, null),
    );
    renderPalette();
    fireEvent.click(await screen.findByTestId("palette-reload-button"));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0]!.message).toBe(
      "Could not reload blocks: 500 Internal Server Error",
    );
  });

  it("opens the reload menu from a section header right-click", async () => {
    vi.mocked(listBlockMetadata).mockResolvedValue(registry());
    vi.mocked(reloadBlocks).mockResolvedValue(reloadResponse());
    renderPalette();
    await sectionHeaders();
    fireEvent.contextMenu(screen.getAllByTestId("palette-user-section-header")[0]!);
    fireEvent.click(screen.getByTestId("palette-menu-reload"));
    expect(screen.queryByTestId("palette-menu")).toBeNull();
    await waitFor(() => expect(vi.mocked(reloadBlocks)).toHaveBeenCalledTimes(1));
  });
});
