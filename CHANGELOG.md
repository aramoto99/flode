# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.35.0] - 2026-05-14 — Add ブロック新規追加 (Sum の矩形版)

ユーザー要望「ADD ブロックを新規作成」。Simulink の Add ブロック (= Sum と
機能同等で形が矩形) と同じ位置付け。

### Added — Backend

- **`pyflw.blocks.mathops.Add`** クラス: `signs` パラメータで符号付き加算
  (`y = Σ sign_i × u_i`)、`Sum` と機能同等。違いは形状のみ (矩形 vs 円)
- `_BUILTIN_METADATA` に `("mathops", "Add", "math.add")` を登録
- `registry_translations.py` で en/ja 翻訳追加 (display_name: Add / 加算 (矩形))
- 単体テスト 11 件 (`tests/blocks/test_add.py`): construction / output / Sum 同等性

### Added — Frontend

- `blockGlyphs.tsx` に `AddGlyph` (= 矩形枠 + 中央「+」)
- `blockShapes.ts` で Add の shape を `rect 48×48` に設定

### Note (scope)

ユーザーは仕様確認時に「SM-A + SM-B 両対応」を選択したが、本 release は
SM-A (= スカラー port) のみ対応。SM-B (= ベクトル / テンソル port) 対応は
別 release で予定 (= 設計検討 + テスト網羅が必要なため別途扱う)。

### Verification

- backend pytest: 812 全 pass (新規 11 件含む)
- typecheck: clean
- vitest: 361 全 pass

## [0.34.0] - 2026-05-14 — glyph 中心ブロック 18 個を正方形 48×48 に

ユーザー要望「配置したブロックは長方形が多いが、正四角形のほうが都合の
いいブロックもある」。glyph (icon) 中心で値表示が不要なシンボリックブロック
を **正方形 48×48** に変更、Simulink 風の「ブロック」感を強化。

### Changed (`blockShapes.ts`)

以下 18 ブロックを `kind: "rect", width: 48, height: 48` に変更:

| カテゴリ | ブロック |
|---|---|
| continuous | Integrator, Derivative |
| discrete | UnitDelay, ZeroOrderHoldDirect |
| mathops | Abs, Sign, MinMax, Saturation |
| sources | Sine, Step, Clock, PulseGenerator |
| sinks | Scope, XYGraph, Terminator |
| logic | RelationalOperator, LogicalOperator |
| routing | Switch |

### Not Changed

横長を要する以下は **default rect (72×40)** のまま:

- `Constant` (= 値文字列 `12345.67` 表示)
- `Ramp` (= 斜線 icon が横長)
- `RateTransition` (= sample-time pair の表示余地)

既存の特殊形 (`Gain` 三角形 / `Sum`/`Product`/`Divide` 円 / `Mux`/`Demux` bar /
`Inport`/`Outport` 台形 / `TransferFunction` etc rect-wide / `Subsystem`)
は変更なし。

### 既存モデルへの影響

保存済み `.flw.json` モデルの `layout.w / layout.h` 上書きは引き続き有効
(= ユーザーが過去にリサイズしたブロックは見た目を保つ)。新規追加 + リサイズ
未指定のブロックのみ新サイズに従う。

### Verification

- typecheck: clean
- vitest: 361 全 pass (`blockShapes.test.ts` 7 件含む)

## [0.33.3] - 2026-05-14 — Gain アイコンが「再生ボタン」に見える問題を修正

ユーザー指摘「ライブラリの Gain が再生マークみたいになっている」。

### Root Cause

`GainGlyph` ([blockGlyphs.tsx:87-92](pyflw/web/frontend/src/lib/blockGlyphs.tsx#L87))
が三角形 polygon を **`fill="currentColor" opacity="0.15"` で薄く塗りつぶし** +
輪郭線、の二重描画にしていた。塗りつぶしがあるため YouTube 等の再生ボタン
▶ に見えていた。

### Fixed

- 塗りつぶし polygon を削除し、Sum / Product 等と同じく **輪郭線のみ** に統一。
  Simulink の Gain ブロックも線画 (三角形枠 + 中央の `k` 値) なので整合性が
  向上

## [0.33.2] - 2026-05-14 — BlockPalette のエントリの角丸を撤廃

ユーザー要望「ライブラリ表示のブロックの角の丸みを完全に削除、角ばった
感じにしてほしい」。Simulink Property Inspector 風 design system の原則
「`rounded` は使わない (or 1-2px に留める)」とも整合。

### Changed

- `BlockPalette.tsx` の built-in + Library 両セクション内ブロックエントリ
  (outer + glyph 内側) から `rounded-sm` を撤廃 → 完全に角ばった矩形に

`rounded-md` (= search input / section header) は今回スコープ外。必要であれば
別 release で対応。

## [0.33.1] - 2026-05-14 — Library セクション (`.flwlib.json` 由来) の violet 装飾を撤廃

v0.33.0 で per-block color を撤廃したが、`BlockPalette` の Library セクション
(= `.flwlib.json` 由来のカスタムサブシステム集) には **violet** が残っていた
(= 旧版で built-in と区別するため hardcode)。built-in と統一する。

### Changed

- `BlockPalette.tsx` の Library セクション内 violet を全て slate に置換:
  - section header text: `text-violet-600` → **`text-slate-500`** (= built-in
    の category header と同色)
  - count badge: `bg-violet-100 text-violet-700` → **`bg-slate-100 text-slate-500`**
  - entry hover: `hover:border-violet-300 hover:bg-violet-50/50` →
    **`hover:border-blue-300 hover:bg-blue-50/50`** (= built-in と同 hover)
  - glyph border / color: `border-violet-200 text-violet-600
    group-hover:border-violet-400` → **`border-slate-200 text-slate-600
    group-hover:border-blue-400`**
  - "LIB" バッジ: `bg-violet-100 text-violet-700` → **`bg-slate-100 text-slate-500`**

Library と built-in の視覚的区別は **section header の「Library · 名前」
プレフィクス + 「LIB」バッジ** で行う (= 色なしでも判別可能)。

## [0.33.0] - 2026-05-14 — per-block color を撤廃 (= ライブラリのジャンル別色付け廃止)

ユーザー討議「ジャンルが増えたら color palette をどう管理する? そもそも色は
必要か?」→ **撤廃**を決定。理由:

1. **メンテナンスコスト**: 旧 `_BUILTIN_METADATA` は entry 行ごとに color を
   hardcode しており、同カテゴリで揃えるのは暗黙の慣習 (= drift しがち)
2. **palette 管理問題**: 新カテゴリ追加時に既存と衝突しない色を考える必要
3. **色覚多様性 (a11y)**: 8 色 palette は緑/紫/青/赤が見分けにくい組み合わせ
4. **design system 整合**: Simulink Property Inspector 風は「白 + 黒線 icon」
   が基調。色付き glyph は web-app 然とした見た目になっていた

### Removed — Backend (API 後方互換性破壊)

- **`BlockMetadata.color` field を削除** (`pyflw/server/registry.py`)
- **`_BUILTIN_METADATA` の tuple を 4 要素 (cat, name, icon, color) → 3 要素**
  (cat, name, icon) に縮小
- **`_resolve_metadata_fallback` の戻り値も 3-tuple** に変更
- **`metadata_to_dict` から `"color"` key 削除** → `GET /api/v1/blocks` の
  response から消える (= 旧 frontend は color が undefined になる、撤廃)
- `_block_color` class attribute サポートも廃止 (3rd-party 拡張は影響あり)

### Changed — Frontend

- `types/api.ts` の `BlockMetadata.color` を削除
- `BlockPalette.tsx`: glyph 色を `text-slate-600` Tailwind class で固定
  (旧 `style={{ color: b.color }}` 撤去)
- `BlockNodeView.tsx`: `color = "#475569"` 固定 (= slate-600)
- `diagramConverter.ts`: node data に color を流さない
- `QuickAdd.tsx`: 非 active 行を slate-600 固定

カテゴリの視覚的区別は `BlockPalette` の **section header + collapse** で
引き続き機能 (= 色なしでも判別性は十分)。

### Test 修正

- `tests/server/test_blocks_registry.py`: `"color"` key の存在チェックを削除し、
  逆に **`"color" not in entry`** をアサート (= 撤廃を恒久化)
- frontend mock fixture 4 ファイル (`autoSplice.test.ts` /
  `blockI18n.test.ts` / `dynamicPorts.test.ts` /
  `portShapeValidate.test.ts`) から `color: "..."` 行を削除

### Verification

- backend pytest (server + core): 578 全 pass
- typecheck: clean
- vitest: 361 全 pass

## [0.32.3] - 2026-05-14 — Diagram の初期表示で過度な拡大を抑制

ユーザー指摘「ダイアグラムのデフォルトの拡大率が少し大きい」。React Flow の
`fitView` は zoom 上限なしのため、ノードが少ないモデルだと過剰に拡大される
傾向があった。

### Changed

- `DiagramCanvas.tsx` で `fitViewOptions={{ maxZoom: 1.0, padding: 0.2 }}` を
  指定。100% を超えないように zoom を制限し、ノード周囲に 20% の余白を確保

## [0.32.2] - 2026-05-14 — Scope のデフォルト見た目を UI design system に合わせて整理

ユーザー指摘「グラフのデフォルトがダサい」。旧デフォルトは tick label が
ブラウザ標準フォントで大きく、"t [s]" が中央に大きく表示、軸色が薄すぎ
(`#94a3b8` = slate-400) で「素の uPlot」感。Simulink Property Inspector 風に
整える。

### Changed (`ScopeView.tsx` の `buildOptions`)

- **フォント明示**: `axes[].font = "11px system-ui, ..."` /
  `labelFont = "10px system-ui, ..."`。Canvas 描画なので CSS が効かず、
  options で指定しないと browser default の sans-serif になっていた
- **軸ラベル色**: `#94a3b8` (slate-400) → **`#64748b` (slate-500)**
  (= 旧は薄すぎて読みづらかった)
- **X 軸 label "t [s]" のサイズを小型化**: `labelSize: 14` /
  `size: 28` / `labelGap: 0` で軸領域全体をコンパクトに
- **Tick** を明示的に描画: `ticks: { stroke: "#cbd5e1", width: 1, size: 4 }`
- **Y 軸** も同様: `size: 38` で密度を上げる
- **デフォルト線幅**: `1.5` → **`1.25`** (= per-signal 設定が無いときの値、
  ユーザーが per-signal で個別指定すれば上書き)

色 palette (`FALLBACK_COLORS` = blue-500 → red-500 → emerald-500 ...) は変更
なし。複数 signal 時の判別性を維持。

### Verification

- typecheck: clean
- vitest: 361 全 pass

## [0.32.1] - 2026-05-14 — Scope のホイールクリック (middle button) ドラッグで pan

ユーザー要望: グラフをホイールクリック (= middle button hold) で掴んで動かすと、
ウィンドウ移動ではなく**プロット領域**を pan できるようにしたい。Simulink の
Scope は pan tool ボタン経由だが pyflw では即時 pan に bind (= simulink には
合わせない、明示的なユーザー判断)。

### Added

- **`UPlotChart.tsx`** に middle button (`button === 1`) hold + drag の pan
  handler を追加 (= `mousedown` 開始 + document-level `mousemove`/`mouseup`)
- 画面 px 差分を `bbox.width/height` ベースで data 単位に変換、X / Y 両軸の
  `setScale` を同時更新 (= 「コンテンツを掴んで引っ張る」感覚)
- ブラウザの middle-click auto-scroll カーソルを `preventDefault` + `auxclick`
  抑止で完全に殺す
- ドラッグ中は `cursor: grabbing`

### Verification

- typecheck: clean
- vitest (uPlotChart.test): 13 件全 pass

## [0.32.0] - 2026-05-14 — ブラウザネイティブ alert/confirm/prompt をデスクトップ風モーダルに置換

ユーザー要望: `window.alert/confirm/prompt` を出すと chrome のネイティブ
ダイアログ (= 「127.0.0.1:8770 の内容」と表示される素朴な dialog) が表示され、
デスクトップアプリ風 UI と整合しない。Simulink Property Inspector 風の独自
モーダル (= `DialogShell` primitives) に置換する。

### Added

- **`src/lib/dialogService.ts`** (新規) — Promise ベースの singleton:
  - `dialog.alert(message, options?)` → `Promise<void>`
  - `dialog.confirm(message, options?)` → `Promise<boolean>`
  - `dialog.prompt(message, options?)` → `Promise<string | null>`
  - 同時に複数 dialog を出さず、queue で順次表示
  - `subscribeDialog` / `getCurrentDialog` / `resolveCurrentDialog` で
    React 外 (= `commands.ts` 等) からも呼べる
- **`src/components/DialogHost.tsx`** (新規) — `useSyncExternalStore` で active
  dialog を購読し、kind に応じて `AlertDialog` / `ConfirmDialog` / `PromptDialog`
  を render。すべて `inspector.tsx` primitives (`DialogShell` /
  `PrimaryButton` / `SecondaryButton` / `DangerButton` / `INPUT_CLS`) を使用、
  ui-design-system.md 準拠
- i18n キー: `dialog.alert.title` / `dialog.confirm.title` / `dialog.prompt.title`
  / `dialog.button.ok` / `dialog.button.cancel` (ja/en)
- vitest unit test (`tests/dialogService.test.ts`) — 12 件 (queue / resolve /
  subscribe / options 受け渡し / 並列呼出し時の順次表示)

### Changed

- **`App.tsx`** root に `<DialogHost />` を mount
- **`window.alert/confirm/prompt` 全 30 箇所を `await dialog.*` に置換**:
  - `lib/commands.ts` (4 alert + 1 confirm)
  - `components/FileBrowser.tsx` (8 alert + 2 confirm + 2 prompt)
  - `components/Launcher.tsx` (2 alert + 1 prompt)
  - `components/MenuBar.tsx` (4 alert + 1 confirm + 1 prompt)
  - `components/Modal.tsx` (1 confirm = `SaveAsPathDialog` overwrite 確認)
  - `lib/useExternalChangesPoll.ts` (1 confirm = 外部変更 reload 確認)
- 既存 test (`fileBrowser.test.tsx` / `useExternalChangesPoll.test.tsx`) で
  `window.confirm` を spy していた箇所を `dialog.confirm` の spy に追従
- `MenuBar.tsx` のローカル state を `dialog` → `modal` に rename
  (= import `dialog` との shadowing 解消)

### Scope Note (= 別 release で対応)

旧 `Modal.tsx` 内の専用 dialog (`SaveAsPathDialog` / `DirtyConfirmDialog` /
`AboutDialog` / `KeyboardShortcutsDialog`) は今回スコープ外。これらは
`rounded-lg` / `shadow-2xl` の古い design のままで、後続 release で
`inspector.tsx` primitives に移行予定。

### Verification

- typecheck: clean
- vitest: **361 全 pass** (新規 12 件 + 既存追従 3 件 + 既存 346 件)

## [0.31.11] - 2026-05-13 — FileBrowser ヘッダーの click toggle を撤去

ユーザー要望: ヘッダーの「ワークスペース」テキストをクリックするとペインが
閉じるが、同じ機能が左端 Activity Bar の File アイコンにあり冗長 (誤操作の元)。

### Changed

- FileBrowser ヘッダーのテキスト button を `<span>` (= 表示のみ) に変更
- ▸ / ▾ の折りたたみインジケータを撤去
- `!collapsed && (...)` の内部 guard を撤去 (= App.tsx 側の
  `{!workspaceCollapsed && sidebarMode === "file" && <FileBrowser />}` で
  既に外側 guard 済、二重ガードだった)

### Note

`workspaceCollapsed` state 自体は撤去しない。`ActivityBar` / `useShortcuts` /
`commands` から引き続き制御するための共有 state として維持。

## [0.31.10] - 2026-05-13 — Shift+クリックも個別 toggle 動作に

ユーザー要望: Shift を押しながら個別クリックで selectedPaths に追加・解除
できるようにしたい。

### Changed

- **CwdEntryRow.onClick**: 既存の `Ctrl/Cmd` 判定を `Ctrl/Cmd/Shift` に拡張
  (= 1 行変更)。Shift+クリックでも Ctrl+クリックと同じ toggle 動作
  (= `onToggleSelection` 呼出し) になる

### Note

旧 `DirectoryNode` / `TreeEntry` (= v0.31.0 で flat list 化したときに残置した
dead code) は対象外。実機で render されていないため触らない。

## [0.31.9] - 2026-05-13 — FileBrowser のコピー / 貼り付け (Ctrl+C / Ctrl+V) + backend `/files/copy` API

ユーザー要望「全選択 / 矩形選択 / コピー」の Phase 3 (= 最終)。

### Added — Backend

- **`POST /api/v1/files/copy?from=<rel>&to=<rel>`** を新設。`shutil.copy2` /
  `shutil.copytree` で同一 workspace 内 src → dst 複製。`dst` の親は
  `parents=True` で auto-create、`dst` 自身は `exist_ok=False`。
  - 204: 成功 (body なし)
  - 400: src/dst が workspace root、src == dst
  - 403: path traversal
  - 404: src 不在
  - 409: dst 既存
  - 500: I/O エラー
- `TestCopy` 9 件 (= ファイル単体 / ディレクトリ再帰 / 各エラー分岐 / 親 auto-create)

### Added — Frontend

- **`copyFile(from, to)`** API client (`src/api/filesApi.ts`)
- **クリップボード state** (FileBrowser 内 `useState<string[]>`)。OS clipboard
  とは独立。`preventDefault` で OS 操作と非干渉
- **Ctrl+C / Cmd+C**: selectedPaths (空なら selectedFilePath) をクリップボードに
  保存
- **Ctrl+V / Cmd+V**: クリップボードの各 path を現在の cwd 配下に複製。複製名は
  `generateCopyName` で衝突回避 (= `model.flw.json` → `model (copy).flw.json` →
  `model (copy 2).flw.json` …)。二重拡張子 `.flw.json` を 1 つの ext として扱う

### 使い方

```
1. アイテムを Ctrl+クリック or 矩形ドラッグで複数選択
2. Ctrl+C  ← クリップボードに記憶
3. (任意) breadcrumb で別フォルダへ cd
4. Ctrl+V  ← 現在の cwd に複製
```

### Verification

- typecheck: clean
- vitest: 349 全 pass
- pytest: 66 全 pass (TestCopy 9 件追加 + 既存 57)

## [0.31.8] - 2026-05-13 — FileBrowser に marquee (矩形ドラッグ) 選択を追加

ユーザー要望「全選択 / 矩形選択 / コピー (削除を便利にするため)」の Phase 2。
複数アイテムを drag-rectangle で囲んで一括選択し、Delete で一括削除できる。

### Added

- **空白部分から左マウスドラッグ → 矩形選択**: drag 中は半透明の青枠
  (`border-blue-500/60 bg-blue-300/20`) overlay を描画、mouseup で矩形と
  各 row の `getBoundingClientRect()` が重なる path を `selectedPaths` に
  まとめて設定 (= 既存集合を置換)
- **空白クリック (= drag 距離 < 4 px) で選択クリア** (JupyterLab 流)

### Implementation Notes

- marquee state は `CwdView` 内に保持 (`marqueeStart` / `marqueeCurrent`)、
  document-level の `mousemove` / `mouseup` listener を `useEffect` で
  attach。drag が FileBrowser 外に出ても追従する
- 各 `CwdEntryRow` の `<li>` に `data-pyflw-path` 属性を付与、
  `querySelectorAll('li[data-pyflw-path]')` で衝突判定対象を取得
- 既存の HTML5 file drag-drop (= `selectedPaths` 集合まとめて移動) は li 内
  でしか開始しないため、空白からの marquee と非干渉
- 新規 prop `CwdView.onReplaceSelection: (paths: string[]) => void` を導入、
  FileBrowser 側で `setSelectedPaths(new Set(paths))` に bind

### Verification

- typecheck: clean
- vitest (fileBrowser.test): 全 pass

## [0.31.7] - 2026-05-13 — Ctrl+A 全選択 + Delete で multi-delete

ユーザー要望「コピー / 全選択 / 矩形選択 (削除を便利にするため)」のうち、
**削除に直結する全選択 + multi-delete** を先行リリース。marquee (矩形ドラッグ
選択) と copy/paste は後続 release で別途対応。

### Added

- **Ctrl+A (Cmd+A)**: 現在の cwd 内の全 entry を `selectedPaths` に追加
  (= React Query cache から即時取得、再 fetch なし)
- **Delete (multi 対応)**: `selectedPaths` が非空なら一括削除、空なら
  `selectedFilePath` を単一削除に fallback。一括削除は **1 回の confirm**
  で「N 個のアイテムを削除しますか?」と表示、OK で順次 `deleteFile` 実行、
  途中失敗は summary alert
- i18n キー: `filebrowser.confirm_delete_many` (ja/en)

### Verification

- typecheck: clean
- vitest: 349 全 pass

### 次の release

- v0.31.8 (予定): ドラッグで矩形選択 (marquee selection)
- v0.31.9 (予定): Ctrl+C / Ctrl+V でコピー / ペースト (backend copy API 追加)

## [0.31.6] - 2026-05-13 — FileBrowser のファイル操作ショートカットキー (Delete / Enter / Escape) 追加

ユーザー要望: ワークスペースでアイテム選択中に F2 以外のキー
(Delete / Enter / Escape) も動くようにしたい。

### Added

- **Delete / Backspace**: 選択中ファイルを削除 (= 既存の `handleDelete` を呼ぶ、
  confirm dialog 経由)
- **Enter**: 選択中ファイルを開く (= 既存の `handleOpen` を呼ぶ。dirty 時は
  `DirtyConfirmDialog` 経由)
- **Escape**: 選択クリア (selectedFilePath = null, selectedPaths = ∅)
- F2 = 既存どおり rename

### Changed

- **F2 を含むキーボード handler を global `window.addEventListener("keydown")`
  から FileBrowser ルート div の `onKeyDown` に移管**。ルート div を
  `tabIndex={-1}` + `outline-none` で focusable にし、`onMouseDown` で focus
  を取る。これにより
  - Diagram canvas など FileBrowser 外でキーを押しても誤発火しない
  - JupyterLab 流「アイテム選択中はファイル操作ショートカットが有効」UX が成立
  - `document.activeElement` が input/textarea のときは全ショートカット無効
    (= 既存 F2 の振る舞いを継承)

### Verification

- typecheck: clean
- vitest (fileBrowser.test): 全 pass

## [0.31.5] - 2026-05-13 — 新規フォルダ prompt のデフォルト値 "subdir" を削除

ユーザー要望: 新規フォルダ作成 prompt のデフォルト文字列 "subdir" が
入っているのは邪魔 (= 全選択して消してから打ち直す必要があり面倒)。

### Changed

- `handleNewFolder` の `window.prompt` 第 2 引数 (= デフォルト値) を削除し、
  空欄から入力させる動線に変更
- `handleNewFile` 側は `untitled.flw.json` を据え置く (= `.flw.json` 拡張子の
  タイピング省略テンプレートとしての価値を維持、untitled 自体は v0.31.1 で
  prompt 化済のためディスク汚染問題はない)

## [0.31.4] - 2026-05-13 — `mkdir` API の status code を 204 に統一 (フォルダ作成後の自動更新を修正)

v0.31.3 で「新規フォルダ」アイコンを追加した直後にユーザーが発見した bug:

```
Mkdir failed: Failed to execute 'json' on 'Response': Unexpected end of JSON input
```

フォルダ自体は作成されるが、エラー dialog が出て、`refresh()` も呼ばれないため
FileBrowser が自動更新されない (= 手動で 🔄 を押すまで反映されない)。

### 根本原因

- backend `POST /api/v1/files/mkdir` が **`Response(status_code=201)` + 空 body** を返却
- frontend `_fetch` は **204 No Content のみ** 空 body を許容 (= `response.json()`
  を呼ぶ)、201 を受けると JSON parse で「Unexpected end of JSON input」エラー
- エラーで `await refresh()` がスキップ → 画面更新されない連鎖

### Fixed

- **backend `mkdir` を `Response(status_code=204)` に変更** (= 既存 `DELETE` と
  同じ pattern に統一)。frontend `_fetch` は 204 で undefined を return するため
  エラーが起きず、`await refresh()` が走り FileBrowser が自動更新される
- 対応する `tests/server/test_files_api.py` の `TestMkdir` を 201 → 204 に更新

### Verification

- pytest: TestMkdir 6 件全 pass
- (frontend mkdir API client は変更なし、`_fetch` が undefined 早期 return)

## [0.31.3] - 2026-05-13 — FileBrowser ヘッダーに新規ファイル/フォルダ アイコン追加 + 右クリック context menu の発火範囲修正

JupyterLab 流の FileBrowser に寄せる UX 改善。ユーザー指摘:

1. サブフォルダ作成の動線が**右クリック context menu の中だけ**で発見性が低い
2. **FileBrowser のヘッダーや余白で右クリックすると、ブラウザのデフォルト
   context menu が出てしまう** (= カスタム menu の発火範囲が `CwdView` の
   outer div に限定されており、ヘッダー / 折り畳み時の div では拾えなかった)

### Added

- **FileBrowser ヘッダーに「新規ファイル」「新規フォルダ」アイコンボタン**
  (= Refresh アイコンと並ぶ 3 つの SVG アイコン)。クリックすると `prompt` を
  経て現在の `fileBrowserCwd` 直下にエントリ作成、JupyterLab toolbar と同じ動線
- **Refresh ボタンを SVG アイコン化** (`⟳` テキスト → `RefreshIcon`)。
  3 ボタンの視覚的一貫性を確保
- i18n キー追加: `filebrowser.action.new_file` / `filebrowser.action.new_folder`
  (ja/en)

### Fixed

- **FileBrowser ルート div に `onContextMenu` を付与**し、ヘッダー / 余白で
  右クリックしてもカスタム context menu が出るように修正。`handleContextMenu`
  が `preventDefault` + `stopPropagation` するため、ブラウザのデフォルト
  context menu は確実に抑止される。発火時の対象 path は現在の
  `fileBrowserCwd` (= ディレクトリ扱い)

### Verification

- typecheck: clean
- vitest: 全 pass

## [0.31.2] - 2026-05-13 — cleanup コマンド後の FileBrowser 自動 refresh

v0.31.1 で追加した「untitled 整理」コマンドは backend で delete したが、
**frontend の FileBrowser cache を invalidate していなかった** ため、
削除後に画面が更新されず手動 🔄 が必要だった。修正。

### Fixed

- **`cleanupUntitled` 内で `queryClient.invalidateQueries({ queryKey:
  ["files-tree"] })` を呼ぶ**: 削除完了後に FileBrowser が自動で再 fetch、
  画面が即座に更新される

### Changed

- **`src/lib/queryClient.ts` を新規作成**: `new QueryClient(...)` を module
  export に切り出し、React component 外 (= `commands.ts` 等) からも
  invalidate できるようにする
- `src/main.tsx` から `queryClient` 定義を削除、`./lib/queryClient` から
  import するように変更 (= QueryClientProvider に渡す唯一インスタンス)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.31.1] - 2026-05-13 — New file の untitled 自動連番を廃止 + 一括クリーンアップ

v0.31.0 までは `Launcher` / `MenuBar` の "New file" 押下で `nextUntitledFilePath`
経由で `untitled1, untitled2, ... .flw.json` がディスクに自動連番で書き込まれ、
削除しないと無制限に蓄積するバグ (= ADR-0041「ファイル自身が真実」の副作用)。
ユーザー要望で A + C の修正:

### Changed (A: 自動連番廃止)

- **Launcher.handleNew / MenuBar.handleNew** の挙動を変更:
  - 旧 v0.31.0: `nextUntitledFilePath()` で N+1 を取り即 putFileContent
  - 新 v0.31.1: **`window.prompt` でファイル名をユーザーに明示要求**、空 /
    Cancel で **no-op** (= ディスク書き込みなし)
  - 入力ファイル名が `.flw.json` で終わっていない場合は自動付与
  - 作成先は **現在の cwd** (= FileBrowser breadcrumb に従う、JupyterLab 流)
- `nextUntitledFilePath` の import を撤去 (backend API は残置、不要)

### Added (C: 一括クリーンアップコマンド)

- **CommandPalette に新規コマンド**: 「未使用の untitled ファイルを整理」/
  "Clean up unused untitled files" (Category: Workspace)
- 動作:
  1. `fileTree("")` で workspace root の直下を列挙
  2. `^untitled\d*\.flw\.json$` にマッチし、かつ **現在 tabs[] に開かれていない**
     ファイルを抽出
  3. 個数 + 先頭 20 件を確認 dialog で表示、ユーザー承認で順次 `deleteFile`
  4. 成功 / 失敗を集計 alert
- 安全策: workspace root の直下のみ対象 (= サブフォルダ内の untitled は除外)、
  開いている tab は除外
- i18n: `command.workspace.cleanup_untitled` (ja/en)

### 操作シナリオ

```
# 既存の大量 untitled を掃除:
1. Ctrl+Shift+P でコマンドパレット
2. 「未使用の untitled」or "cleanup" で検索
3. Enter → 「Delete 113 unused untitled file(s)?」 confirm
4. OK → 全削除

# 今後の untitled 増殖を防止:
- Launcher / MenuBar の「New」を押す → prompt で名前を要求
- 空入力 or Cancel = 何も作成されない
```

### 既知の制約 (= 次の minor 候補)

- **真の解決 = JupyterLab 流の memory-only unsaved** は別途 ADR で扱う (=
  本 hotfix では即決ファイル化を維持、prompt で明示化に留める)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.31.0] - 2026-05-13 — FileBrowser を JupyterLab 流 cwd フォーカス型に書き換え

ユーザー要望「ワークスペースのカレントディレクトリ移動」に対応。FileBrowser を
**展開ツリー → cwd フォーカス型 flat list** に書き換え。JupyterLab の
FileBrowser 流儀 (= フォルダクリックで cd、breadcrumb で上に戻る) に統一。

### Added

- **store `fileBrowserCwd: string`** + `setFileBrowserCwd` action (= 現在
  表示中のフォルダ相対パス、root は `""`、session 内のみで永続化なし)
- **`CwdView` 新規 component** (`src/components/FileBrowser.tsx` 内):
  - **breadcrumb 行** (上部): home icon (= root へ) + ↑ (= 上へ) + segment
    クリックで cd
  - **flat list 本体**: cwd 配下の entries を 1 階層表示、directory を先頭・
    file を後ろにソート
  - フォルダクリック = **cd (= cwd 切替)**、ファイルクリック = 開く (既存挙動)
  - drag-drop / Ctrl+クリック multi-select / 右クリック context menu /
    inline rename はすべて維持
- **`CwdEntryRow` 新規 component**: 各 entry を 1 行で描画、folder と file の
  挙動を統合
- i18n: `filebrowser.breadcrumb.root` / `filebrowser.breadcrumb.up` /
  `filebrowser.empty_folder` (ja/en)

### Changed

- **FileBrowser のメンテナンスモデル**: 旧 v3.9.x の `<DirectoryNode>`
  自己再帰ツリーを撤去 (= component は維持するが import から外し dead code 化、
  ロールバック互換のため温存)
- フォルダの **自動展開** (= v0.30.2 の `defaultExpanded={depth <= 1}`) は
  撤去 (= flat list では概念が無い)
- test 更新: `tests/fileBrowser.test.tsx` の auto-expand 期待を「v0.31.0
  flat list なので auto-expand しない」に更新

### 操作感の変化

- 旧 v3.9.x: フォルダの ▸ 矢印クリックで展開 / ▾ で折りたたみ、深い階層は
  入れ子ツリー表示
- 新 v0.31.0: フォルダをクリックすると **中に入る** (= Finder / Explorer
  と同じ感覚)、breadcrumb で上に戻る、root へワンクリック (home icon)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.30.5] - 2026-05-12 — sidebar / Inspector の境界線を細く (1px)

ユーザーから「Inspector / Workspace とダイアグラムの境界線が太すぎる」
フィードバック。visual 5 px + aside border 1 px = 計 6 px の二重境界を解消し、
**1 px の細い境界**に統一。drag のヒットエリアは ResizeHandleX の overlay
(= ±4 px) で確保済なので、操作性は変わらない。

### Changed

- App.tsx の grid template columns で **drag handle 列を 5 px → 1 px** に縮小
  (= 列 2 = sidebar handle、列 4 = inspector handle 両方)
- 左 sidebar の `<aside>` から **`border-r border-slate-300`** を撤去
  (= ResizeHandleX が境界の役割、二重境界排除)
- 右 Inspector の `<aside>` (展開時 + 折りたたみ時両方) から
  **`border-l border-slate-300`** を撤去 (= 同上)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.30.4] - 2026-05-12 — Inspector 横幅を drag で可変に

v0.26.10 で左サイドバーに導入した自前 drag handle と同じ pattern を Inspector
にも適用。Inspector の左境界を drag で横幅変更可能。localStorage に永続化。

### Added

- **store `inspectorWidth: number`** + `setInspectorWidth(px)` action +
  localStorage `pyflw.inspector_width` 永続化
- **`ResizeHandleX` に `direction?: "left" | "right"` prop**: 旧 = 左サイドバー
  (= 右 drag で拡大、direction="left" 既定) / 新 = Inspector (= 右 drag で
  縮小、direction="right" で delta 反転)
- **App.tsx grid template 6 列構成**:
  `activity-bar / sidebar / sidebar-handle / main / inspector-handle / inspector`
  collapsed 時は対応 handle を 0 px に潰す
- 既定値: 200 〜 600 px の range、初期 280 px (= 旧固定値と同じ)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.30.3] - 2026-05-12 — scopes-stack を × で閉じた後の復活経路を追加

v0.30.2 で Diagram pane の split ボタンを hide した結果、ユーザーが scopes-stack
を × で閉じた後に **再表示する手段が消失** していたバグを修正。

### Added

- **Diagram pane に「+ Scope」ボタンを追加** (= `PaneTitleBar.onShowScopes`):
  - 表示条件: **scopes-stack 葉が SplitTree に存在しない** かつ **モデルが
    Scope/XYGraph ブロックを持つ** 場合のみ
  - クリックで `splitPane("diagram", "vertical", "scopes-stack", "after")` を
    実行、scopes-stack pane が下に復活
  - 表示位置: Diagram pane タイトルバー右、split/unsplit/detach の各 icon
    button より目立つ「+ Scope」ラベル付きボタン (= 復活経路の発見性を高める)
- i18n: `workspace.show_scopes_area` / `workspace.show_scopes_area.short`
  (ja/en)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.30.2] - 2026-05-12 — v0.30.0 ユーザー要望反映 (revert 中心、6 件対応)

v0.30.0 リリース直後のユーザー動作確認フィードバック 6 件を全対処。Stage 3 で
導入した一部変更を **revert** + 新仕様 (Scopes pane タブ切替) を追加。

### Fixed

- **バグ修正: sidebar 閉じると Diagram / Scope / Inspector も消える** (要望 #4):
  原因 = grid 5 列定義に対し JSX が collapsed 時に 3 子要素しか描画せず、
  main / Inspector が左詰めで列 2-3 (= 0 px) に流れ込んでいた。Column 1
  (`<aside>`) と Column 2 (drag handle) を **常時描画**、内容のみ条件付きに
  修正

### Changed

- **FileBrowser: depth 1 まで自動展開** (要望 #5): 旧 v0.30.1 までは root のみ
  自動展開、ユーザーから「階層表示がない」フィードバック。`TreeEntry` の
  `defaultExpanded` を `depth <= 1` に変更し、root 直下のフォルダも起動時に
  展開。深い階層はユーザー click で展開
- **Inspector を sidebar 単独 UX に revert** (要望 #1): ADR-0052 §(2) で
  追加した **3 mode (sidebar/pane/float) を撤去**、v3.8.x までの「列 4 で
  折りたたみ 2 値」に戻す。`InspectorFloatPanel` + mode 切替 select を撤去、
  store の `inspectorDockMode` state は無効化 (= UI からは触れない、localStorage
  キーは互換のため残置)
- **Scope ダブルクリック挙動を float 即開きに revert** (要望 #2): ADR-0052
  §(3) で「docked split 昇格」に変更したが、v0.30.2 で **ADR-0044 当初挙動
  (= `openScopePanel`)** に戻す。pane タイトルバーの detach ボタンは残置
  (= scope:<id> 葉が SplitTree に既に存在する場合の経路として温存)
- **`ScopesStack` をタブ切替化** (要望 #3): 旧 = 縦並べで全 Scope 表示、
  新 = **タブヘッダー + 単一 Scope 表示** (Simulink Scope 風)。`<button
  role="tab">` で scope_id を横並びに、active scope のみ uPlot 描画。
  active scope は local state で管理 (= 永続化なし、entries 変化で先頭に
  fallback)
- **Diagram pane の split right / split down ボタンを hide** (要望 #6):
  Diagram は常に 1 pane で運用、分割系アクションは scopes-stack タイトル
  バーで操作。Diagram pane への drag-drop の 4 端 split も **no-op** に追加

### Test update

- `tests/fileBrowser.test.tsx`: `defaultExpanded={depth <= 1}` 仕様に
  合わせて test 名と assertion を更新 (= fetch 回数 1 → 2、`""` + `"controllers"`)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.30.1] - 2026-05-12 — v0.30.0 code-reviewer 指摘の hotfix

v0.30.0 直後の code-reviewer agent 指摘 (= MUST 0 / SHOULD 3 / NITS 2) を全対処。

### Fixed

- **`useShortcuts` の cleanup で `Ctrl+K` prefix timeout が残留** (SHOULD #1):
  unmount 時に `clearTimeout` を呼ぶよう `return () => {...}` を拡張。HMR 等の
  頻繁 remount で symptom 顕在化リスクを排除
- **`renameTabFilePath` で SplitTree の `tab:<oldPath>` 葉が追従しない**
  (SHOULD #2): ファイル rename 後に SplitTree 内の pane 表示が「閉じられて
  います」と誤表示される問題。新 helper `renameLeaf(tree, old, new)` を
  `src/lib/splitTree.ts` に追加、`renameTabFilePath` action 内で連動呼出し
- **`onDragLeave` が子要素への移動で発火** (SHOULD #3): drop indicator
  overlay のチラつきを防止、`e.currentTarget.contains(e.relatedTarget)` で
  内側への移動を無視

### Changed

- **`ScopesStack` の dead code 解消** (NITS #4): 三項演算子の両辺が同じキー
  だった部分を平坦化、将来分岐の余地はコメントで明示
- (NITS #5) `InspectorFloatPanel` の `rounded` は `ScopePanelContainer` と
  既に統一済 (= 確認のみ、変更なし)

### Verification

- typecheck: clean
- vitest: 349 全 pass
- ADR-0052 §Confidence の判断者への問いに反する事項なし

## [0.30.0] - 2026-05-12 — Workspace JupyterLab Stage 3 = Drag-to-split-tab + Inspector pane 化 (ADR-0052)

ADR-0052 採択 (Phase 6c Stage 3、Accepted 2026-05-12)。**Phase 6c の最終 Stage**:
タブを drag → 別 pane に split / Inspector を 3 mode (sidebar/pane/float) で
配置 / Scope ダブルクリックを docked split 昇格に semantics 変更。Option A
中範囲、新規依存追加なし、ADR-0044 `react-rnd` 共用継続 (Scope detach +
Inspector float)。

### Added

- **Drag-to-split-tab** (`src/lib/dnd.ts`):
  - `application/x-pyflw-tab-ref` MIME で TabStrip のタブを drag 可能
  - WorkspaceSplit 内で drop 位置 (= 5 領域: center + 4 端) 判定 + drop
    indicator overlay (青半透明)
  - 4 端 drop で `splitPane(target, orientation, "tab:<filePath>", position)`
    を呼んで新 pane 化
  - center drop は Stage 3 MVP で no-op (= タブ追加 semantics は Stage 4+)
- **新 paneId**: `"tab:<filePath>"` / `"inspector"` の 2 種 (= ADR-0052 §(2)(3))
- **Inspector pane 化** (3 mode):
  - **`sidebar`** (= 既定、現状温存): 列 4 で 24/280 px 折りたたみ
  - **`pane`**: WorkspaceSplit 内に `inspector` 葉として配置、列 4 を 0 px に
  - **`float`**: react-rnd で main 上に浮かせる
  - 列 4 ヘッダに mode 切替 `<select>` を追加 (`Property Inspector` primitives
    準拠、segment 風 button は使わない)
- **`InspectorFloatPanel` コンポーネント** (`src/App.tsx` 内): Inspector を
  Rnd wrapper で float 描画 (= ScopePanelContainer と同じ pattern を再利用)
- **PaneTitleBar に「detach」ボタン** (`src/components/PaneTitleBar.tsx`):
  Scope pane で Rnd float に切替 (= 既存 ADR-0044 openScopePanel を再利用)
- **キーボードショートカット 4 種**:
  - `Ctrl+\` = active tab を右に split (= 現タブの `tab:<filePath>` 葉を
    diagram pane の右に horizontal split で追加)
  - `Ctrl+K Ctrl+\` = 同上、上下分割で
  - `Ctrl+K I` = Inspector mode を cycle (sidebar → pane → float → sidebar)
  - `Ctrl+K Z` = Zen mode toggle (= sidebar / inspector 両折りたたみ)
  - `Ctrl+K` は **1.5 秒 prefix mode** (= VSCode 流の 2-stroke shortcut)
- **store state 追加**:
  - `inspectorDockMode: "sidebar" | "pane" | "float"` + `setInspectorDockMode`
  - localStorage `pyflw.inspector_dock_mode` に永続化 (= workspace 横断、
    モデル切替で変更しない)
- **`splitPane` action に `position?: "after" | "before"` 引数追加**: 既定
  `"after"` で従来挙動温存、drag-drop の left/top drop で `"before"` を使う
- **`closeTab` action 拡張**: タブ閉じで SplitTree の `tab:<filePath>` 葉も
  クリーンアップ (= dangling leaf 防止)
- **i18n キー 14 個追加** (ja/en):
  - `workspace.pane.title.inspector`
  - `workspace.detach`
  - `workspace.inspector.mode.{label,sidebar,pane,float}`
  - `workspace.tab_leaf.{switch_to,not_open}`
  - `workspace.shortcut.{split_right,split_down,zen_mode,inspector_mode}`

### Changed

- **Scope ダブルクリック挙動 (= semantics 変更、breaking)** (ADR-0044
  §Amendments §(1)):
  - **旧 v3.8.x**: Scope ダブルクリック → react-rnd float panel が即開く
  - **新 v0.30.0**: Scope ダブルクリック → `scope:<id>` 葉として
    WorkspaceSplit に追加 (= docked split 昇格、Stage 1 と同 path)。float は
    pane タイトルバーの **「detach」ボタン** で明示切替
- ADR-0040 §Amendments §(3) で Phase 6c Stage 3 = ADR-0052 確定、Phase 6c
  完了マッピング (= Stage 1 + 2 + 3 すべて Accepted + 実装完了)

### Migration

- **既存 localStorage キー破壊なし**: `pyflw.workspace_layout.*` /
  `pyflw.scope_panel.*` / `pyflw.workspace_collapsed` /
  `pyflw.inspector_collapsed` / 等 全て維持
- 新規追加キー: `pyflw.inspector_dock_mode` (= 既定値 `"sidebar"`、未設定なら
  従来挙動)
- ロールバック互換: v3.8.x への戻しで動作可能

### Out of scope (Stage 3 で実装しない)

- **タブ追加 semantics** (= center drop): Stage 3 MVP では no-op、Stage 4+ で
  タブ群 (tab group) 化を再評価
- **`pyflw.inspector_float_geometry.<hash>`** 永続化: 初期は Rnd default
  geometry のみ、利用者要望で hotfix 候補
- **Inspector mode dropdown の `<PaneTitleBar>` 内表示** (= ADR-0052 §(2) で
  予告): Stage 3 v0.30.0 では列 4 ヘッダのみ、pane mode 時の pane タイトル
  バー内 dropdown は v3.9.x で追加候補

### Verification

- typecheck: clean
- vitest: 349 全 pass (= v0.29.4 と同件数)
- bundle 実測は build 時、+20-30 KB gzip 目標
- ADR-0040 §Amendments §(3) で Phase 6c Stage 3 = ADR-0052 確定、Phase 6c の
  3 段すべて Accepted + 実装完了 (= Phase 6c 概ね完了)
- ADR-0044 §Amendments §(1) で Scope dblclick semantics 変更 + Rnd 役割再定義
- **Phase 6c 完了** (= ADR-0045 + 0051 + 0052 すべて Accepted + リリース済)

### Phase 6c 完了

本 release で **Phase 6c (Workspace JupyterLab convergence)** の 3 段階すべて
が Accepted + 実装完了。Stage 4 以降の予約はなし (= 目標 JupyterLab UX
converge は概ね達成)。Phase 6 全体の完了は **Phase 6b (Codegen + GPU)** の
完了 (= 新 ADR-0050) 待ち、別系列。

## [0.29.4] - 2026-05-12 — CommandPalette Block 追加: display_name の i18n 対応 (ADR-0028)

v0.29.2 で追加した Block 追加コマンドの **表示名と検索キーワードを現在 locale
に対応** させる。ADR-0028 で定義済の `display_name_i18n` (= blocks schema v2)
と既存 `searchableDisplayNames` helper を再利用、コード追加は最小。

### Changed

- **CommandPalette Block 追加コマンドのラベル表示**:
  - 旧 v0.29.2: `meta.display_name` を直接表示 (= 常に英語 "Constant" "Gain" 等)
  - 新 v0.29.4: `localizedDisplayName(meta)` 経由で現在 locale の翻訳を表示
    (= ja UI なら「定数」「ゲイン」等、未翻訳なら英語フォールバック)
- **検索キーワードを両言語対応**:
  - 旧 v0.29.2: `display_name` + lowercase 版
  - 新 v0.29.4: `searchableDisplayNames(meta)` で **ja + en + type_path 末尾**
    を全て検索対象に (= ja UI でも英語名 "Sum" で検索可能、Simulink 経験者の
    セーフネット、ADR-0028 §(4))
- **CommandPalette `useMemo` deps に `i18n.language` を追加**: 言語切替で
  registry が再構築され、Block コマンドのラベルが新言語で再 resolve される

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.29.3] - 2026-05-12 — CommandPalette Block 追加: Quick Insert (選択中 block の右に配置 + auto-connect)

v0.29.2 の block 追加コマンドを **Simulink "Quick Insert" 流儀** に強化。
キャンバスで block を 1 個選択した状態で `Ctrl+Shift+P` → 「Gain」→ Enter で
**選択中 block の右に Gain を配置 + 自動連結** + 新 Gain を選択状態に。
更に `Ctrl+Shift+P` → 「Scope」→ Enter で **Gain → Scope** 直列追加。
キーボードのみで「Constant → Gain → Scope」のような信号フロー連鎖が組める。

### Added

- **selectedNodeIds が 1 個のとき**:
  - 新 block の position = selected block の **右 +140 px、同 y 座標**
  - 新 block の `default_n_inputs > 0` かつ `is_container=false` のとき
    **auto-connect**: `selected.out[0] → new.in[0]` の edge を追加
  - 新 block を **selection に切替** (= 連続 Quick Insert で直列に追加可能)
- **selectedNodeIds が 0 or 複数のとき**:
  - 従来の bounding box heuristics で配置 (= 既存 block の右下 +140 px)
  - auto-connect は無し

### 操作シナリオ

```
[初期 canvas に Source ブロック 1 個]
1. Source を選択 (single click)
2. Ctrl+Shift+P → "Gain" → Enter
   → Source の右に Gain 配置 + Source.out[0] → Gain.in[0] 接続 + Gain 選択
3. Ctrl+Shift+P → "Scope" → Enter
   → Gain の右に Scope 配置 + Gain.out[0] → Scope.in[0] 接続 + Scope 選択

結果: Source → Gain → Scope の直列接続が完成 (= マウスドラッグ不要)
```

### 制約

- Source 系ブロック (= n_inputs=0) を追加する場合は auto-connect 無効
- Subsystem (is_container=true) は内部接続が複雑なので auto-connect 対象外
  (= 通常通り bounding box heuristics で配置のみ)
- src_idx / dst_idx は固定で 0 のみ (= multi-port block は最初の port を使う、
  ユーザーが別 port に繋ぎ直すには手動で edge を引き直す)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.29.2] - 2026-05-12 — コマンドパレットに Block 追加コマンド (動的、registry 30+ 件)

v0.29.0 コマンドパレットを更に拡張。`Ctrl+Shift+P` → 「Gain」「constant」「Sum」
「ブロック」等で検索すると、backend block-registry の全ブロック (= 30+ 種)
が動的コマンドとして表示され、Enter で **canvas に追加** できる。
BlockPalette の drag-drop の代替経路として、キーボードのみで block 追加が
可能に。

### Added

- **`Command.category` に "block" 追加**: 30+ 件の block を grouping、
  category 表示順は最後 (= 初期表示で他 category を圧迫しない)
- **`buildBlockAddCommands(blocks)`** (`src/lib/commands.ts`):
  - 各 block_metadata に対し `block.add:<type_path>` command を生成
  - 検索キーワード = `display_name` / `type_path` / `category` / `tags` を結合
  - action: `addBlockToEditing(block, position)` を呼ぶ (= BlockPalette drag
    と同じ store action)
  - **位置決定**: 既存 block の bounding box の右下 + 140 px offset、無ければ
    (100, 100)
  - **enabled**: `editingModel !== null` (= ファイル未開時は disabled 灰色)
- **CommandPalette が block-registry を tanstack-query で fetch**: 既存
  BlockPalette / DiagramCanvas と同じ `queryKey: ["blocks-registry"]` を
  共有、`staleTime: 60 min` で cache。
- i18n: `command.category.block` (ja "ブロック" / en "Block") /
  `command.block.add` (ja "ブロックを追加" / en "Add block")

### 操作方法

- `Ctrl+Shift+P` → "gain" 入力 → ↓ で選択 → Enter で Gain ブロックが canvas
  に追加
- `Ctrl+Shift+P` → "Sum" → 候補 1 件のみ表示 → Enter で即追加
- 日本語検索も対応: "ブロック" でカテゴリ全体表示

### 制約 (= 既知)

- block 追加位置は **既存配置の右側 heuristics**、ユーザーが任意位置に置くには
  追加後に手動ドラッグが必要 (= drag-drop なら drop 位置で決まる)
- block の `display_name` は現状 ja/en に翻訳されない (= ADR-0028
  `display_name_i18n` 未参照、英語の "Constant" "Gain" 等で表示)。検索は
  日本語 keyword で引ける

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.29.1] - 2026-05-12 — コマンドパレットに Recent Files 動的コマンドを追加

v0.29.0 コマンドパレットを拡張、現在のワークスペースの **Recent Files を動的
コマンドとして列挙** する。`Ctrl+Shift+P` 起動 → 「最近」「recent」「ファイル名」
等で検索 → Enter で開ける。Launcher の Recent list と同じデータソース
(`pyflw.recent.<workspaceHash>`) を共有。

### Added

- **`Command.dynamicSuffix?: string`** field 追加: 共通 labelKey で複数行を
  出す動的 command 用 (= "最近のファイルを開く: models/foo.flw.json" 形式)
- **`buildRecentFileCommands(workspaceHash, limit=10)`**: localStorage の
  Recent Files を最大 10 件 (= Launcher 5 件より広く) 動的 command 化
- 各 Recent command は **直接 REST 呼出し** (= `getFileContent` +
  `openFileInTab`) で synthetic keyboard event を経由しない
- 検索キーワード: `recent`, `open`, `最近`, `開く`, ファイルパス全体 +
  小文字版 (= 「spring」「PID」等の partial match で引ける)
- i18n: `command.file.open_recent` (ja: "最近のファイルを開く" / en: "Open recent")

### Changed

- **CommandPalette の `registry` を `useMemo(..., [workspaceHash, open])`** に変更:
  modal を開くたびに最新の Recent を読み直す (= 別 modal 中に Recent 追加が
  あっても次回 open 時に反映)
- 表示ラベル組み立てを `${t(labelKey)}: ${dynamicSuffix}` 形式に対応 (= 静的
  command は従来通り `t(labelKey)` のみ)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.29.0] - 2026-05-12 — コマンドパレット (Ctrl+Shift+P) を追加

JupyterLab / VSCode 流のコマンドパレットを実装。`Ctrl+Shift+P` で modal 表示、
検索 input + コマンドリスト + キーボード操作で **既存機能を名前検索で発火**
できる。ADR 不要 (= 既存機能の発見性向上、新規機能追加ではない)、新規依存
追加なし。

### Added

- **`Ctrl+Shift+P` でコマンドパレット起動** (= 新規 shortcut)
- **`CommandPalette` modal** (`src/components/CommandPalette.tsx`):
  - 検索 input (= 上部) + コマンドリスト (= 下部、最大 400 px 高)
  - **substring match 検索** (= label + keywords を結合して contains 判定、
    大文字小文字無視、英日混在対応)
  - **↑/↓ で選択移動、Enter で実行、Esc で閉じる**
  - 選択中は青ハイライト (`bg-blue-600 text-white`)、disabled command は灰色
  - **マウス hover で selection 移動** + クリックで実行
- **Command registry** (`src/lib/commands.ts`): 12 個の主要コマンドを登録
  - File: New / Save
  - Edit: Undo / Redo (= `canUndo` / `canRedo` で disabled 判定)
  - Simulation: Run / Stop
  - View: Sidebar toggle / File mode / Library mode / Search (path / content) /
    Inspector toggle
- **i18n キー 19 個追加** (ja/en): `command.palette.{title,placeholder,no_match}` /
  `command.category.{file,edit,simulation,view,workspace}` /
  `command.{file.new,file.save,edit.undo,edit.redo,simulation.run,...}`
- **store state `commandPaletteOpen: boolean`** + `setCommandPaletteOpen` action

### 実装方針

- 各 command の `action` は **store action 直接呼出し** か **synthetic
  `KeyboardEvent` を `window.dispatchEvent`** で既存 shortcut path を再利用
  (= `useSimulation` / `useAutoSave` 等の hook を CommandPalette 内部で
  重複 instance 化しない、`setTimeout(0)` で modal close 後に発火)
- 検索は **fuzzy ライブラリ追加なし** (= substring contains で MVP、ライブラリ
  追加は bundle 増分要因なので避ける、利用者数 12 個では substring で十分)
- `keywords` field で **英日両言語の検索ワード** を併用可能
  (例: `["new", "新規", "作成"]`)

### 出し分け表示

- コマンド行は `[CATEGORY] Label ............... Ctrl+Shortcut` の 3 領域
- category は左の uppercase 表示 (= タグ風)、shortcut は右寄せ (= mono font)
- 検索結果無し時は「該当するコマンドがありません」/ "No matching commands"

### a11y

- modal は `role="dialog" aria-modal="true" aria-label="コマンドパレット"`
- list は `role="listbox"`、行は `role="option" aria-selected={isSelected}`
- 検索 input に `aria-label` 付与
- ↑/↓ ナビゲーション中も focus は input から外れない (= スクリーンリーダーが
  追従可能、`scrollIntoView({block: "nearest"})` で選択行を可視範囲に)

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.28.2] - 2026-05-12 — FileBrowser multi-select (Ctrl+クリックで複数選択 + drag-drop 一括移動)

ADR-0041 §論点 7-A で v0.19.0 送りとされていた multi-select (Shift / Ctrl)
リストのうち **Ctrl+クリック** を実装。v0.28.1 の drag-drop と組み合わせると
**複数アイテムを一括で別フォルダへ移動** できる。ADR 不要 (= incremental
UX 改善)、新規依存追加なし。

### Added

- **Ctrl+クリック (Cmd+クリック on macOS) で選択 toggle**: ファイル / フォルダ
  どちらにも対応。Ctrl+クリック時はファイルを開かず / フォルダを展開せず、
  selection 集合に追加 or 削除のみ
- **複数アイテムの drag-drop 一括移動**: drag start 時 selectedPaths に
  drag source が含まれていれば集合全体を移動、含まれていなければ単体を移動
  (= VSCode 流儀)
- **multi-select の視覚フィードバック**: selected アイテムは `bg-blue-100`
  ハイライト、drag-over 中のフォルダ行は `bg-blue-200` (= drop target は
  multi-select より強調)
- **a11y**: 選択中アイテムに `aria-selected={true}` 付与

### Changed

- **drag MIME 形式を JSON 配列化**: 旧 v0.28.1 = 単一 path 文字列 / 新 v0.28.2 =
  JSON 配列 `["path1", "path2"]`。旧形式 (= JSON parse 失敗で単一文字列扱い)
  も読み取り fallback で後方互換
- **`handleMove(sources: string[], targetDir)` に拡張**: 各 source を順次処理、
  禁止条件 (= 自分のサブツリーへの drop) は 1 件でもあれば最初に alert、
  各 source の失敗は記録して最後に集計 alert
- **移動完了後に selectedPaths をクリア** (= multi-select state を引きずらない)
- **通常クリック (= modifier なし)** は従来挙動を維持 (= ファイル開く /
  フォルダ展開)、selectedPaths は明示的に Ctrl+クリックで組み立てる

### Out of scope (Stage 3 候補へ送り)

- **Shift+クリック** = 範囲選択 (= 直前 anchor から連続選択): tree 構造での
  実装が複雑なため Stage 3 で再評価
- **キーボード `Ctrl+A` で sidebar 全選択**: 既存 `Ctrl+A` は Diagram canvas
  の「全 block 選択」に bind 済、conflict のため未実装
- **Esc で selection クリア**: 既存 `Esc` は drillUp / selection クリアに
  bind 済、FileBrowser scope での micro-action は別 ADR で整理

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.28.1] - 2026-05-12 — FileBrowser drag-drop でフォルダ間移動

ADR-0041 §論点 7-A で v0.19.0 送りとされていた drag-drop によるフォルダ間
移動を実装 (SPEC-0001 §機能要件 Phase 6+ #56 stretch (e) を回収)。新規依存
追加なし、HTML5 drag-drop API を自前で組む。ADR 不要 (= incremental UX 改善)。

### Added

- **FileBrowser tree item の drag source 化** (`TreeEntry` / `DirectoryNode`):
  - **ファイル** = drag source として外に出せる、drop は受け付けない (= file
    の上に file を置く semantics は未定義のため)
  - **フォルダ** = drag source + drop target の両対応 (= 別のフォルダから
    ここへ移動できる + 自分自身を他へ移動できる)
- **drop target の視覚フィードバック**: drop 中のフォルダ行に `bg-blue-100`
  ハイライト (= drag over の `<li>` で `isDragOver` state を切替)
- **root への drop**: 左サイドバー container 全体を drop target にし、root
  ディレクトリへの移動も可能 (= top-level に戻せる)
- **MIME type `application/x-pyflw-path`**: 外部ファイル drop を排除するため
  pyflw 固有 MIME を採用 (= ブラウザ標準 file drop は無視される)
- i18n キー: `filebrowser.move.descendant_forbidden`

### Changed

- **`handleMove(sourcePath, targetDir)` 関数を `FileBrowser` 内に追加**:
  - 同じ親 dir 内 → no-op
  - 自分自身に drop → no-op
  - 自分のサブツリーに drop → 禁止 (= 無限再帰防止、alert で通知)
  - 既存 `POST /api/v1/files/rename` を流用 (= `from` / `to` 形式、UNIX `mv`
    相当の semantics、別 dir への移動も受け付ける)
  - 移動後の `tabs[]` path も追従 (= dir 移動なら配下 file の path も再構築)
  - 開いてるモデルは etag/mtime を再 fetch

### 操作方法

- ファイル/フォルダを **マウスでドラッグ** → 別フォルダの上で **ドロップ**
  → 移動完了
- **root に戻す** = サイドバー内の空き領域 (= 一覧の末尾 / 全体) にドロップ
- 同名ファイルが移動先に存在する場合は backend が 409 を返し alert で通知
- 移動はサーバ側で atomic、失敗時は元の場所に残る

### Verification

- typecheck: clean
- vitest: 349 全 pass

## [0.28.0] - 2026-05-12 — Workspace JupyterLab Stage 2 = Activity bar + Launcher (ADR-0051)

ADR-0051 採択 (Phase 6c Stage 2)。Workspace UI を JupyterLab/VSCode 流の
「activity bar + sidebar mode 切替 + Launcher」構造に刷新する大規模改修。
**見た目が大きく変わる初の Stage** (= Stage 1 = v0.27.0〜3.6.2 は内部レイアウト
機能の追加で見た目変化は限定的だった)。

### Added

- **左端 activity bar** (`src/components/ActivityBar.tsx`): 32 px 固定幅、
  File / Library / Search の 3 mode をアイコンで切替。selected mode に左
  2 px の青い accent bar 表示 (= VSCode 風)。`<button role="tab">` で a11y
  確保 (= ADR-0030 規律継承)
- **Launcher** (`src/components/Launcher.tsx`): ファイル未選択時に旧
  EmptyState を置換。Start tile (New / Open) + Recent 上位 5 件 list +
  「Show all...」リンク (= sidebar mode を file に遷移)
- **sidebar mode state** (`store.sidebarMode`): `"file" | "library" |
  "search"`、localStorage `pyflw.sidebar_mode` に永続化、起動時復元
- **キーボードショートカット 2 件追加**:
  - `Ctrl+B` = sidebar 全体 toggle (= `workspaceCollapsed` 反転、VSCode 流)
  - `Ctrl+Shift+E` = sidebar mode を file に切替 + sidebar 展開
- **i18n キー 10 個追加** (ja/en): `activity.aria.tablist` /
  `activity.{file,library,search}` / `launcher.section.{start,recent}` /
  `launcher.tile.{new,open}` / `launcher.recent.{empty,show_all}`

### Changed

- **App.tsx grid 4 列 → 5 列**: 列 0 = activity bar (32 px 固定) を新規追加。
  `workspaceCollapsed` 時は列 1〜2 を 0 px に潰し activity bar のみ表示
- **左 sidebar 列 1 の中身を mode で切替**: 旧「FileBrowser 上 + Library
  palette 下の縦分割」(= `react-resizable-panels` の `id="pyflw.workspace_library_split"`)
  を撤去、`sidebarMode` 値に応じて FileBrowser / BlockPalette / SearchPanel
  のいずれか 100% 表示。旧 localStorage キーは温存 (= ロールバック互換)
- **`SearchPanel` を overlay → sidebar mode inline 描画に refactor**:
  ADR-0043 で確立した overlay (= `Ctrl+P` / `Ctrl+Shift+F` で開く modal) を
  撤去、sidebar 列 1 内に inline 描画。`pyflw:open-search` event は維持
  (= kind 切替 + input focus のみ)
- **`Ctrl+P` / `Ctrl+Shift+F` semantics 変更** (= ADR-0043 §Amendments §(1)):
  旧 = overlay 起動 / 新 = sidebar mode を search に切替 + sidebar 展開 +
  検索 kind 設定 + input focus

### Out of scope (Stage 2 では実装しない)

- **Inspector pane 化** (= 列 4 折りたたみ 2 値を WorkspaceSplit 統合):
  Stage 3 で drag-to-split-tab と一括設計 (= ADR-0052 予約)
- **Launcher を別タブで開ける拡張** = Stage 3 候補
- **Activity bar Running mode** (= 実行中 sim プロセス管理) = Phase 6b 完了後
- **Templates セクション** = 内蔵テンプレ機能が未実装、別 ADR 必要
- **`Ctrl+Shift+L` を Library mode 切替に充てる候補** = ブラウザ shortcut
  との誤押しリスクで棄却、Library mode は activity bar クリックのみ
- **ダークモード** = **7 回目の永続的 out-of-scope 再確定**

### Migration

- **既存 localStorage キーは破壊なし**: `pyflw.workspace_collapsed` /
  `pyflw.inspector_collapsed` / `pyflw.left_sidebar_width` /
  `pyflw.workspace_library_split` (= 休眠だが温存) /
  `pyflw.last_active.<hash>` / `pyflw.recent.<workspaceHash>` /
  `pyflw.workspace_layout.*` / `pyflw.scope_panel.*` 等 全て維持
- 新規追加キー: `pyflw.sidebar_mode` (= 既定値 `"file"`)
- **ロールバック互換**: v3.6.x への戻しで動作可能 (= 新キーは無視される、
  旧キーは温存)

### Verification

- typecheck: clean
- vitest: 349 全 pass (= v3.6.x と同件数)
- bundle 増分は本 release で実測予定 (= +20-30 KB gzip 目標、累積 ~270 KB)
- ADR-0040 §Amendments §(2) で Phase 6c Stage 2 = ADR-0051 確定、ADR-0043
  §Amendments §(1) で Search panel semantics 変更を永続化

### Phase 6c 残: Stage 3 = ADR-0052 予約

Stage 2 リリース後の利用者フィードバックを 1〜2 週間収集後、Stage 3
(= drag-to-split-tab + Inspector pane 化 + `ScopePanelContainer` (Rnd) 廃止
/ 統合判断) に着手。

## [0.27.2] - 2026-05-12 — Workspace multi-pane Stage 1 UX: 個別 Scope 分離ボタン (UX-4)

ADR-0045 §(1) 必須スコープ「個別 Scope を pane として独立分離する semantics」を
**より直感的な操作** にする UX 改善。

### Changed

- **`scopes-stack` 内の各 Scope に小型ヘッダー + 「個別分離」ボタン** を追加 (UX-4):
  - 従来: `scopes-stack` 全体の split-down ボタンを押すと「stack 内の最初の
    scope が暗黙的に別 pane へ移動」する動作。ユーザーから見た intent と不一致
    (= stack 自体を分割したつもりが、1 個の scope だけが移動)
  - v0.27.2: 各 Scope の上に **scope_id + 「個別分離」アイコンボタン** が出る。
    クリックすると **その scope** が `scope:<id>` 葉として独立分離される
- ScopesStack のレイアウトを `flex-col gap-2` のシンプルな縦並びから、各 Scope を
  `border border-slate-200` の小型カード化 (= ヘッダー 20 px + 本体)

### Added

- i18n キー: `workspace.scopes_stack.split_out_scope`
  - ja: 「この Scope を個別ペインに分離」
  - en: "Move this Scope to its own pane"
- `ScopesStack` に `onSplitOutScope: (scopeId: string) => void` prop
- `SplitOutButton` 小型コンポーネント (= アイコン + tooltip)

### Verification

- typecheck: clean
- vitest: 349 全 pass
- ADR-0045 §(1) 必須スコープ「個別 Scope を独立分離」は v0.27.0 で既に達成済、
  本 hotfix は **同 semantics をより直感的な UI で達成** する追加改善

## [0.27.1] - 2026-05-12 — Workspace multi-pane Stage 1 の UX hotfix

v0.27.0 リリース直後の UX 改善 2 点。実装範囲は ADR-0045 §(1) Stage 1 必須スコープ
の範囲内 (= 機能追加ではなく既存挙動の親切化)。

### Changed

- **空 `scopes-stack` ペインの説明文を状況別に出し分け** (UX-1): 従来は「すべての
  Scope が個別ペインに分離されています」のみ表示していたが、シミュレーション未
  実行時 (= scope buffer 未受信) と全分離済の 2 状態を区別:
  - sim 未実行: 「シミュレーションを実行するとここに Scope のグラフが表示されます」
  - 全分離済: 「すべての Scope が個別ペインに分離されています (右上の「分割解除」で閉じられます)」
- **split / split-down ボタンを hide ではなく disabled で表示** (UX-3): 押せない
  状態でも灰色で残し、tooltip (= `title` 属性) に「なぜ押せないか」を表示:
  - `scope:<id>` 葉から → 「Scope ペインはこれ以上分割できません」
  - sim 未実行で `scopes-stack` 空 → 「シミュレーションを実行すると Scope を別ペインに分離できます」
  - 全分離済で `scopes-stack` 空 → 「すべての Scope が既に別ペインに分離されています」
- a11y: disabled ボタンに `aria-disabled` + `cursor-not-allowed` + 灰色文字

### Added

- i18n キー 5 個追加 (ja/en):
  `workspace.scopes_stack.no_data` / `workspace.split.disabled.scope_leaf` /
  `workspace.split.disabled.run_simulation` / `workspace.split.disabled.all_separated`
- `PaneTitleBar` に optional `disabledSplitReason?: string | null` prop

### Verification

- typecheck: clean
- vitest: 349 全 pass (= v0.27.0 と同じ件数、新規 i18n キーは i18n.test.ts の
  「ja/en key 集合一致」テストで自動検証)
- bundle: 微増 (= 文言追加のみ、削減は無し)

### 補足

UX-2 「Scope pane タイトルを block name で表示」は調査結果 cancel:
`BlockEntry` には `name` フィールドが存在せず、`block.id` (例: `Scope_1`) が
そのまま Simulink でいう Block Name に相当するため、現状の挙動 (= scope_id raw
表示) が正しいことを確認。

## [0.27.0] - 2026-05-11 — Workspace JupyterLab Stage 1 = multi-pane split (ADR-0045)

ADR-0045 採択。**Phase 6c (Workspace JupyterLab convergence) Stage 1** として
Workspace の multi-pane split を導入。`<main>` 内の Diagram + Scope を縦/横
任意配置可能に、SplitTree state を localStorage に永続化する。新規依存追加なし
(= 既存 `react-resizable-panels@4.11.0` のネスト split を活用)。

### Added

- **Multi-pane split layout** (ADR-0045 §(1)): 各 pane タイトルバーの
  「split right」「split down」「unsplit」アクションで Diagram pane と Scope
  群を縦/横自由配置。2 段ネスト split (= 3 ペイン構成) までサポート。
- **SplitTree データ構造** (`src/lib/splitTree.ts`): `LeafNode` /
  `SplitNode` 型と純関数 (`insertSplit` / `removeLeaf` / `normalizeTree` /
  `serializeTree` / `deserializeTree` / `migrateFromScopeSplit` /
  `chooseInitialTree`)。Vitest 全カバレッジ。
- **`WorkspaceSplit` コンポーネント** (`src/components/WorkspaceSplit.tsx`):
  SplitTree を再帰的に `<PanelGroup>` + `<Panel>` に展開し、Diagram pane に
  対応する slot div を提供。
- **`PaneTitleBar` プリミティブ** (`src/components/PaneTitleBar.tsx`):
  Property Inspector 風の細バー (h-6) + split / unsplit icon button。
- **localStorage 永続化キー** (`src/lib/storageKeys.ts`):
  `pyflw.workspace_layout.<workspaceHash>.<b64url(modelPath)>` (= モデル別
  粒度、ADR-0044 と同じ慣例)。ADR-0044 `pyflw.scope_panel.*` と共通の
  `b64urlEncode` ヘルパーに統一。
- **i18n 文字列** (ja/en): `workspace.pane.title.diagram` /
  `.scopes_stack` / `workspace.split.right` / `.down` / `workspace.unsplit` /
  `workspace.split.handle.{horizontal,vertical}`。
- **E2E spec** (`tests/e2e/workspace-multipane.spec.ts`): 初期 layout 表示 /
  split 操作 / unsplit / 永続化リロード / floating panel 並存 の 5 シナリオ。

### Changed

- **`DiagramCanvas`** (ADR-0045 §(6)): optional `portalTarget?: HTMLElement`
  prop を追加。指定時は `createPortal` で DOM を当該要素に投影 (= React tree
  上の親は `<ReactFlowProvider>` 直下のまま不変、viewport が SplitTree 再構造
  でも保持される)。
- **`App.tsx`**: `<main>` 内の `<PanelGroup id="pyflw.scope_split">` ブロックを
  `<WorkspaceSplit>` に置換。`<DiagramCanvas portalTarget={diagramPortalEl}/>`
  を `<ReactFlowProvider>` 直下に常時 mount。
- **Zustand store**: `workspaceLayout: SplitTree` state と action
  (`splitPane` / `unsplitPane` / `setWorkspaceSplitRatio` /
  `toggleWorkspaceSplitOrientation` / `resetWorkspaceLayout`) +
  `loadWorkspaceLayout` を追加。

### Migration

- **旧 `pyflw.scope_split` キーからの片方向 migration** (ADR-0045 §(3-D)):
  起動時に旧キーが存在すれば `DEFAULT_TREE_WITH_SCOPES` (= 縦 60/40
  Diagram + scopes-stack) で代用。旧キーは削除しない (= ロールバック対応)。

### Confirmed out-of-scope (Stage 1)

- キーボードショートカット (= Stage 2 で Launcher / activity bar と一括設計)
- 3 段以上のネスト split (= Stage 2 で実需確認後)
- Inspector / FileBrowser / Library palette の pane 化 (= Stage 2 候補)
- drag-to-split-tab (= Stage 3)
- ダークモード (= 永続的 out-of-scope、本リリースで 6 回目の再確定)

### Verification

- typecheck: clean
- frontend vitest: 全 test pass (= splitTree.test.ts 新規 28 ケース含む)
- ADR-0040 §Amendments §(1) で Phase 6c 新設 + Phase 6b ADR 番号繰り下げ
  (旧 ADR-0045〜0049 → 新 ADR-0046〜0050) を確定
- SPEC-0001 §機能要件 Phase 6+ §Phase 6c (N1〜N3) 節を新設

## [0.26.12] - 2026-05-11 — シミュレーション開始時にブロック図のビューポート (zoom + pan) がリセットされる問題を修正

### Fixed

- **シミュレーション実行で React Flow の zoom / pan がリセットされる問題**:
  ``App.tsx`` の center main エリアで、可視 Scope の有無によって
  ``<DiagramCanvas/>`` の親要素を ``<PanelGroup>`` (Scope あり) と素の
  ``<div>`` (Scope なし) で切り替えていたため、Run を押した直後に最初の
  Scope サンプルが届いた瞬間に親要素が変わり、React の reconciliation で
  ``<DiagramCanvas/>`` がアンマウント → 再マウントされていた。再マウント
  された ``<ReactFlow fitView/>`` が初期 fitView を再実行し、ユーザーの
  ビューポートが破棄される。
- ``PanelGroup`` を **常時描画** に変更。canvas 用 Panel を child 0 に固定で
  置き、Scope 用 handle + Panel を後置 sibling として ``hasVisibleScopes``
  でのみ条件付きで描画。Panel 0 (canvas) は常に同じ React tree 位置を保つ
  ため、reconciliation がインスタンスを維持しビューポートが保持される。
- Scope 無し時の Panel 0 ``defaultSize=100``、Scope ありで ``defaultSize=60``
  (= ``react-resizable-panels`` 内部はその差分を吸収して下 Panel に 40 % 割振り)。

### Verification

- typecheck + production build: clean
- frontend vitest: 312 passed
- 手動ブラウザ確認は要 (Claude 側では UI 実機検証未実施)

## [0.26.11] - 2026-05-11 — code-reviewer / security-reviewer 指摘の hotfix

### Security

- **File API ``/api/v1/files/search`` の秘密ファイル除外を強化** (security-reviewer
  指摘): workspace 内に偶発的に置かれている可能性のある credential ファイルを
  hardcoded で検索結果から除外する。
  - ファイル名除外: ``.env`` (+ ``.env.*`` 前綴)、``id_rsa`` / ``id_ed25519`` /
    ``id_ecdsa`` / ``id_dsa``
  - ディレクトリ除外に ``.ssh`` / ``.aws`` / ``.gnupg`` / ``.docker`` / ``.idea``
    を追加 (= 既存の ``.git`` / ``node_modules`` 等と同じ frozenset)
  - これは workspace owner の機密ファイルが** preview として bytes ペイロードに
    含まれてしまう** リスクを潰すため、設定可能 (user override) ではなく **常に
    enforce** する hard-coded list として実装。
- **DoS 緩和** (security-reviewer 指摘):
  - ``q`` パラメータの長さを **256 文字に制限** (= rapidfuzz の WRatio が
    超長文クエリで O(N×M) 退化するのを防止)、超過時は 400 Bad Request
  - **path search を heap-bounded** に変更 (``heapq.heappushpop``): スコア順
    top-N を保持しながら最大 ``limit`` 件しかメモリに保持しない (= 旧実装は
    全マッチを保持してから sort、巨大 workspace で OOM)
  - **content search 1 ファイル ≤ 2 MiB** 制限 (= ``file_path.stat().st_size``
    で事前 skip、bytes load 前に弾く)
  - **fs walk 全体で最大 50,000 ファイルまで visit** (= 万一 excludes を
    すり抜けても探索が無限に続かない、超過後は途中結果を返す)

### Fixed

- **``autoSplice.ts`` ``inputHandleY`` の dead if-branch を削除** (code-reviewer
  指摘): 全 shape kind で同じ式を返す死分岐が、将来 ``BlockNodeView`` が shape
  依存になった時に同期漏れで誤判定する罠だったため、単純な等間隔配置式に統一。
- **``ResizeHandleX`` (左サイドバー drag) に ``setPointerCapture`` を追加**
  (code-reviewer 指摘): drag 開始 element がスクロール等で外れた時にも
  ``pointermove`` を確実に拾い続け、稀に発生する「ドラッグ中断で幅が固まる」
  バグを防止。
- **``TabBar`` / ``TabButton`` に ARIA ``role`` / ``aria-selected`` を付与**
  (code-reviewer 指摘): スクリーンリーダーで tablist として認識されるよう、
  ``role="tablist"`` (+ optional ``aria-label``)、``role="tab"`` +
  ``aria-selected={active}`` を実装。

### Tests

- ``tests/server/test_files_api.py`` に 3 ケース追加:
  - ``test_query_too_long_400`` (= ``q`` 257 文字超で 400)
  - ``test_excludes_env_file_content`` (= ``.env`` ファイルが content search で
    返ってこない)
  - ``test_excludes_ssh_directory`` (= ``.ssh/`` 配下が path / content 双方で
    返ってこない)
- ``test_path_traversal_in_q_does_not_escape`` を強化 (結果 path が ``/`` 始まり
  または ``..`` を含まないことを assert)

### Verification

- ruff check / ruff format --check: clean
- mypy 48 files: clean
- pytest: 1236 passed (回帰なし、+3 新規)
- frontend vitest: 312 passed
- typecheck + production build: clean

## [0.26.10] - 2026-05-11 — 左サイドバー drag resize を自前実装に切替 (react-resizable-panels horizontal が grid 内で機能せず)

### Fixed

- **v0.26.8 / v0.26.9 で導入した左サイドバー横幅 drag resize が動作しなかった
  問題**: ``react-resizable-panels`` の horizontal ``PanelGroup`` を CSS grid
  セル内に置くと Panel の幅変化が反映されないケースがあったらしく、ハンドルを
  ドラッグしても寸法が変わらず、ヒットエリアの拡張 (v0.26.9) でも解決しなかった。
- **自前ドラッグハンドル** (`ResizeHandleX` コンポーネント) に切替:
  - grid template columns に 5 px の専用 column を確保
  - `pointerdown` で window-level `pointermove` / `pointerup` を bind、
    開始時の `clientX` と `leftSidebarWidth` baseline から差分計算
  - store action `setLeftSidebarWidth` で min 160 px / max 600 px にクランプ +
    localStorage `pyflw.left_sidebar_width` に永続化
  - drag 中は ``bg-blue-500`` で明確、`z-20` + `cursor-col-resize` で
    React Flow に pointer event を奪われない
  - 左右 ±4 px の透明ヒットエリアで 13 px 相当の grab zone
- 縦方向の 2 split (Workspace ↕ Library、Canvas ↕ Scope) は引き続き
  ``react-resizable-panels`` 使用 — そちらは flex 親内なので機能している。

### Verification

- typecheck + production build: clean
- frontend vitest: 312 passed (回帰なし)

## [0.26.9] - 2026-05-11 — Resize ハンドルが React Flow に pointer event を奪われていた問題を修正

### Fixed

- **左サイドバーの resize ハンドルをドラッグしても幅が変わらず、React Flow の
  pane selection が発火していた問題**: ``PanelResizeHandle`` の視覚幅が 1 px
  (`w-1` / `h-1`) と細すぎて、ユーザーが掴むつもりが隣接する React Flow canvas
  領域を掴んでしまっていた。
  - 視覚幅は **2 px** に縮小 (`w-0.5` / `h-0.5`)、目視は控えめだが明確
  - その上下 / 左右に **-4 px ずつ拡張した透明な absolute child** を載せ、
    実際の **ヒットエリアを 10 px** に確保 (= 視覚はそのままハンドルを掴みやすく)
  - `z-10` + `cursor-col-resize` / `cursor-row-resize` で event 優先と cursor 表示
  - drag 中は `data-[resize-handle-state=drag]:bg-blue-500` で青強調
- 左 / Canvas 水平ハンドルだけでなく、Workspace ↕ Library と Canvas ↕ Scope の
  vertical ハンドル 2 個も同じパターンに揃えた (= 3 ハンドル全部掴みやすく)。
- 左 Panel の minSize を `"160px"` 文字列から ``12`` (= 12%) 番号に変更 (= 単位
  混在を回避、library が一貫した percentage 計算で処理できる)。

### Verification

- typecheck + production build: clean

## [0.26.8] - 2026-05-11 — 左サイドバーの横幅を drag resize 可能に

### Added

- **左サイドバー (Workspace + Library) と Canvas エリアの境界をマウスドラッグで
  横方向 resize 可能に**: 従来は左サイドバーが 240 px 固定だったが、
  ``react-resizable-panels`` の horizontal ``PanelGroup`` で 1 px 青ハンドルを
  挟み、ユーザーが自由に幅を変えられるようになった。
  - 左サイドバー: defaultSize 18 % / minSize **160 px** / maxSize 45 %
  - Canvas: defaultSize 82 % / minSize **320 px**
- 右側 Inspector はもう片方の collapse 機構を維持する都合で grid column のまま
  (= state-controlled、24 px ↔ 280 px)。Inspector 横幅自体の drag resize は
  Phase 7 以降の課題。

これで window 内 3 種類の split が drag resize 可能:
- 左サイドバー横幅 ↔ Canvas (本リリース、horizontal)
- Workspace ↕ Library (v0.26.6、vertical 左サイド内)
- Canvas ↕ Scope (v0.24.0、vertical 中央)

### Verification

- typecheck + production build: clean
- frontend vitest: 312 passed (回帰なし)

## [0.26.7] - 2026-05-11 — Workspace/Library 分割の最小サイズを pixel 指定 (ヘッダー以下に縮まない)

### Fixed

- **Workspace 部分をヘッダーバーより小さく縮められた問題**: v0.26.6 の minSize は
  `15` (% 指定) で、viewport が低い場合に 24 px のヘッダーバーより小さくなる
  ケースがあった。``react-resizable-panels`` v4 の string-with-units 機能を使い、
  両 panel の minSize を `"48px"` (= header 24 px + 内容 24 px 程度) に切替。
  これでヘッダーは常に完全表示される。

### Verification

- typecheck + production build: clean

## [0.26.6] - 2026-05-11 — Workspace / Library 分割比を drag resize 可能に

### Changed

- **左サイドバー (Workspace / Library) の上下分割比をマウスドラッグで変更可能に**:
  従来は固定 40 % / 60 % だったが、``react-resizable-panels`` で **drag handle**
  (= 上下境界に 1 px の青ホバー帯) を挿入し、ユーザーが直感的にリサイズできるよう
  にした。最小サイズは各 15 %。
- ワークスペースが折りたたみ状態 (`workspaceCollapsed`) のときは旧来の
  「FileBrowser 24 px header + Library 残り全部」の固定レイアウトを維持。

これで `Canvas / Scope` (= v0.24.0) と同じ手法で 3 種類の split が drag resize 可能:
- 左サイドバー: Workspace ↕ Library (本リリース)
- 中央: Canvas ↕ Scope (v0.24.0)

### Verification

- typecheck + production build: clean
- frontend vitest: 312 passed (回帰なし)

## [0.26.5] - 2026-05-11 — Inspector の折りたたみ対応

### Added

- **Inspector パネル (右サイドバー) を折りたたんで描画エリアを広げる**:
  Inspector header の "▶" ボタン (= chevron) で折りたたみ、Canvas が右側 280 px
  分広がる。折りたたみ後は 24 px の細い垂直バーが右端に残り、そこをクリック or
  内部の "◀" ボタンで再展開。バーには縦書きで "Inspector" ラベルも表示する。
- localStorage `pyflw.inspector_collapsed` に永続化 (= `pyflw.workspace_collapsed`
  と同じパターン)。

`workspaceCollapsed` (= 左サイドバー上半分の折りたたみ) と同じ UX なので学習コスト
ゼロ。

### Verification

- typecheck + production build: clean
- frontend vitest: 312 passed (回帰なし)

## [0.26.4] - 2026-05-11 — Inspector のラベル左寄せ + 入力欄が画面右半分に偏らない

### Fixed

- **Inspector で「label + input が右半分に偏って、左半分が空白」だった問題**:
  v0.26.3 で右側の breathing room は確保したが、ラベルを右寄せ column (96px) で
  保持していたため、`"k:"` のような短いラベルは依然 col 96 付近に表示され、
  入力もその右に配置されていた → パネル左半分がほぼ空白という偏った見た目。
- 解決: `PropertyRow` primitive に **`labelAlign?: "left" | "right"`** を追加
  (default は既存の `"right"`、広い modal はそのまま)。`ParameterPanel` だけ
  `labelAlign="left"` + `labelWidth=88` を渡して左寄せ化、入力幅を 140px に
  戻す。これでパネル左端からラベル → 入力 → 右余白の自然な左→右 flow になる。
- 長いラベル (例: `buffer_capacity (int)`) は label cell 内で truncate + hover
  tooltip 表示するよう ``truncate`` + `title=label` を追加 (= layout 崩壊回避)。

`ScopeSettingsDialog` / `ModelSettingsModal` は default の `labelAlign="right"`
のまま (= colon が綺麗に縦揃いするので広い modal では適切)。

## [0.26.3] - 2026-05-11 — Inspector の入力欄が右端に張り付く問題を修正

### Fixed

- **ParameterPanel の入力欄が右端まで延びて窮屈に見える**: Inspector パネル幅は
  280 px 固定で、ラベル 120 px + 入力 `max-w-[160px]` (= flex-1 で実際は ~128 px)
  だと入力ボックスの右辺が panel 右パディングのほぼ直上に位置し、視覚的に窮屈
  だった。``labelWidth`` 120 → 96、入力幅 `max-w-[160px]` → `max-w-[120px]` に
  絞り、入力の右側に ~30 px の明確な breathing room を確保。

ScopeSettingsDialog / ModelSettingsModal は 480〜540 px 幅の modal で同問題は
無いため変更なし (= primitives は共通だが幅の指定が個別)。

## [0.26.2] - 2026-05-11 — E2E hotfix (v0.21.0 から壊れていた Playwright spec を v3.x UI に書換)

### Fixed

- **Playwright webServer 起動失敗**: `playwright.config.ts` が v0.21.0 で削除された
  `--model-dir` を依然指定していたため `pyflw-server: error: unrecognized arguments`
  で立ち上がらず。`--workspace` に置換、health-check URL も `/api/v1/models` →
  `/api/v1/files/workspace_info` に更新。
- **E2E spec 全面書き換え (v3.x UI 適合)**:
  - `smoke.spec.ts`: 旧 ModelList / "Run" button 検証は撤去、新 FileBrowser tree +
    TabStrip + DiagramCanvas viewport を確認する 3 ケースに刷新
  - `parameter-panel.spec.ts`: 旧 "Save" button + "Saved" badge 検証は撤去 (= v3.x
    で auto-save 化、UI badge 廃止)。**ファイル内容の永続化を fs ベースで直接検証**
    する形に書き換え、500 ms debounce + 1.5 s 余裕の wait を入れる
- E2E fixture `minimal_model.flw.json` を schema 0.8 + `layout` 付き + Scope の
  `buffer_mode` / `buffer_capacity` を明示。

E2E ジョブは v0.21.0 以降 "Queued - Waiting to run" のまま動いていなかった (= 6
fail のうち 1 だけ queued だった理由)。本リリースで実際に green になる。

## [0.26.1] - 2026-05-11 — CI hotfix (v0.26.0 で 6 ジョブ赤、ローカル緑)

### Fixed

- **dev extras に ``rapidfuzz`` / ``pathspec`` を追加**: v0.26.0 (= v0.23.0 で追加した
  workspace 検索の依存) で gui extras にのみ追加していたが、CI test job は
  ``[dev]`` のみインストールするため ``tests/server/test_files_api.py::TestSearchFiles``
  が ``ImportError`` で全 collection 失敗していた。
- **mypy ``[type-arg]`` エラー**: ``pathspec.PathSpec`` を generic 型として
  ``pathspec.PathSpec[Any]`` (string forward ref) に annotate (= ``files.py``)。
- **Sphinx ``docs`` ジョブ赤**: ``Scope`` docstring の Args 内に bullet list を
  書いていたため docutils の ``Unexpected indentation`` 警告 → ``-W`` で error 昇格。
  bullet list を散文に書き換えた。
- **ruff lint / format 違反**: ``examples/jax_jacfwd_pid.py`` の unused import +
  f-string プレースホルダーなしを autofix、複数ファイルの format も適用。

ローカルでは ``pytest`` / ``mypy --strict`` / ``ruff`` / ``sphinx`` の 4 段階
チェックを CI と同じ手順で通過することを確認。

## [0.26.0] - 2026-05-11 — Simulink "auto-connect on edge" 対応

### Added

- **エッジ上にブロックを置くと自動接続**: Simulink R2014b〜の "drop on wire"
  / "splice into wire" 動作を再現。SISO (n_inputs=1, n_outputs=1) ブロックを:
  - Palette からエッジ上に **drop** すると、入力 0 と出力 0 がエッジ路上に
    乗っている場合に元エッジが `source → block → target` の 2 本に自動分割
  - 既存の孤立ブロック (= 接続が無いブロック) を canvas 上で **drag stop** した
    位置がエッジ上の場合も同様に自動分割
  - 既に接続を持つブロックの移動は対象外 (= 既存接続の破壊を回避)
  - エッジ複数が match する場合は曖昧として何もしない (= 利用者の手動接続待ち)
- 判定 helper `src/lib/autoSplice.ts`:
  - smooth-step (90° 折れ線) edge を前提に、水平セグメント (source 側 / target 側 /
    縮退時の単一直線) 上の交点判定を実装
  - 許容距離 10 px (`SPLICE_TOLERANCE_PX`)
  - `<input type="text">` 互換、純粋関数で testable
- store action `spliceEdgeWithBlock(oldEdge, blockId)`: 元エッジ 1 本削除 +
  upstream / downstream 2 本追加を **1 history entry** にまとめ、`Ctrl+Z` 1 回で
  完全に元に戻る。

### Verification

- frontend vitest: **312 passed** (= 295 prior + 17 new for autoSplice)
- typecheck + production build: clean

## [0.25.0] - 2026-05-11 — UI デザインシステム確立 + Inspector / ModelSettings 統一

### Added

- **UI primitives `src/components/ui/inspector.tsx`** (新規): 設定 UI / dialog の
  共通 building block。Simulink Property Inspector 風スタイルを SSOT として固定:
  - Layout: `<PropertyGrid>` / `<PropertyRow>` (label 右寄せ + 値、indent 対応) /
    `<SectionDivider>` (uppercase + 横ルール)
  - Dialog: `<DialogShell>` (Escape / 外側 click で close、subtle gradient title bar) /
    `<DialogFooter>` (左 secondary + 右 primary)
  - Tabs: `<TabBar>` + `<TabButton>` (active = 白背景の上面紙)
  - Buttons: `<PrimaryButton>` / `<SecondaryButton>` / `<DangerButton>`
  - Inputs: `<NumberInput>` / `<TextInput>` + `INPUT_CLS` / `SELECT_CLS` /
    `CHECKBOX_CLS` の Tailwind 定数
- **デザインガイド `.claude/docs/ui-design-system.md`** (新規): 採用 / 禁止 idiom、
  カラーパレット、レイアウト定型、reference 実装。
- CLAUDE.md にデザインシステム規約を追記。
- memory `feedback_simulink_native_ui` 追加 (= 今後の UI 実装で primitives 厳守)。

### Changed

- **ParameterPanel (Inspector サイドバー)** を Simulink Property Inspector 風に
  全面 refactor (= 旧 label 上 / 入力下の縦レイアウトを 2 列 PropertyGrid に置換)。
  - BlockHeader (gradient title bar) + section divider ("Layout" / "Parameters" /
    "Read only" / "Mask parameters")
  - native widgets (`<select>` / `<input>` / `<input type="checkbox">`)
- **ModelSettingsModal** を同スタイルに全面 refactor:
  - DialogShell + 3 section ("Solver" / "Step size" / "Tolerance")
  - PropertyGrid で `solver` / `dt` / `dt_base` (auto + indent value) / `rtol` /
    `atol` を整列
  - 旧 `<Field>` (label 上 / 入力 + hint) を撤去
- **ScopeSettingsDialog** を primitives ベースに簡素化 (= 見た目同一、内部のみ
  クリーンアップ)。

### Verification

- typecheck + production build: clean
- frontend vitest: 295 passed (回帰なし、ModelSettings 7 件は新スタイルで再確認済)

## [0.24.6] - 2026-05-11 — 「既定値に戻す」が機能しない不具合修正

### Fixed

- **`resetScopeSettings` が単一 scope の場合に動作しない問題**: object spread
  の挙動を誤解した実装で、最後の 1 件を削除すると `editingModel.scope_settings`
  が元の object 参照のまま残り、Dialog UI でも設定が消えたように見えなかった。
  `delete next.scope_settings` を明示的に呼ぶよう修正。複数 scope の場合は
  v0.24.5 までも動作していた (= 短い dict で上書きされていた)。
- 回帰テスト 9 件を追加 (= ``updateScopeSettings`` の merge / dirty / history、
  ``resetScopeSettings`` の単一 / 複数 / no-op / null model / undo 履歴 push)。

### Verification

- frontend vitest: **295 passed** (= 286 prior + 9 new)
- typecheck + production build: clean

## [0.24.5] - 2026-05-11 — プロット設定 dialog のタブ切替時 window 寸法固定

### Fixed

- **ScopeSettingsDialog のタブ切替で window サイズが上下に伸縮していた問題**:
  Display tab (= manual / log で行数が増減) と Style tab (= 信号数で行数が変動)
  で content 高さがばらつき、タブ切替のたびに dialog が伸び縮みしていた。
  content 領域を固定高さ ``h-[340px]`` に変更し、内容が超える場合はその領域
  内で scroll する。タブ切替時に window 寸法は不変。

### Verification

- typecheck + production build: clean

## [0.24.4] - 2026-05-11 — プロット設定 dialog を Simulink Property Inspector 風に再設計

### Changed

- **ScopeSettingsDialog を Simulink Property Inspector スタイルに再設計**
  (= 旧 v0.24.3 が依然 web app 然としていたため):
  - **タブレイアウト**: Display (表示) / Style (スタイル) の 2 タブ、
    Style タブ header に信号数バッジ
  - **プロパティグリッド**: 「ラベル (右寄せ 140px) | 値入力 (左寄せ)」の
    伝統的な 2 列レイアウト、項目間は 22px 高で密
  - **ネイティブ widget**: `<select>` / `<input type="checkbox">` /
    `<input type="text">` を直接使用 (= 旧 segmented control / switch toggle /
    pill button を撤去)、border 1px slate-400、border-radius は廃止
  - **セクション divider**: 「Y axis」「X axis」「Layout」の小見出しで論理分け
  - **タイトル/フッタ**: subtle gradient で windowy な見た目、OK + Reset to
    defaults ボタンは native dialog 風
  - **Style タブ**: 信号一覧を table-like grid (`#` / Color / Width / Marker)
    で表示、color picker は swatch + hex 表示
  - manual mode の min/max は indent 表示で階層を示唆
  - Escape で close (新規)
  - 信号 0 個のとき「シミュレーション実行してください」表示

### Verification

- typecheck + production build: clean
- frontend vitest: 286 passed (回帰なし)

## [0.24.3] - 2026-05-11 — プロット設定 dialog UI リファイン

### Changed

- **ScopeSettingsDialog の UI を全面刷新** (= 旧版は素朴すぎたため):
  - 2 列グリッド (Y/X/凡例/グリッド) で情報密度向上
  - 各セクションに icon (Y軸 / X軸 / 凡例 / グリッド / 信号)
  - segmented control (= active 強調 + shadow-inner) で軸モード / 凡例位置を選択
  - **switch toggle** (= 旧 plain checkbox → モダンな pill switch) でグリッド on/off
  - 信号行: color swatch + hex 表示 + 線幅 dropdown + **marker dropdown** (= 既定値 none / circle / square / cross、SignalSettings 型を完全活用)
  - color picker: hex 入力フィールド追加、外側クリックで閉じる overlay
  - footer に **「既定値に戻す」** ボタン追加 (= 当該 scope の scope_settings entry を完全削除)

### Added

- `useAppStore.resetScopeSettings(scopeId)` action — 当該 scope の設定を削除
  (= 全フィールド既定値に戻す)。space 効率のため scope_settings dict が空に
  なれば top-level キー自体を削除し JSON 出力を綺麗に保つ。

### Verification

- typecheck + production build: clean
- frontend vitest: 286 passed (回帰なし)

## [0.24.2] - 2026-05-11 — Scope floating panel 表示不具合修正

### Fixed

- **Floating Scope panel のプロットがパネルサイズに追従しない問題**: uPlot は
  options.width / options.height で初期化されるため、設定変更等で uPlot を
  再生成した直後は default 400x192px のままだった。``UPlotChart`` で
  instance 作成直後に親要素サイズへ ``setSize`` を明示的に呼ぶよう修正。
- **Floating Scope panel に "Scope_X" タイトルが二重表示される問題**:
  ``ScopePanelContainer`` の drag handle タイトルを削除し、``ScopeView`` の
  header (= 設定 / 最大化 / 閉じるボタン付き) を drag handle として再利用。
- **Scope 表示が WS スコープバッチごとに uPlot 再生成する性能問題**: 
  ``ScopeView`` の options ``useMemo`` 依存から ``buffer`` 参照を除外、
  Scope ID / 信号数 / 設定変更時のみ再生成するように修正。

## [0.24.1] - 2026-05-11 — Scope ホイールズーム

ADR-0044 §論点 7 で予告したカーソル/ズーム/パンのうち、ホイールズームを実装。

### Added

- **Scope / XYGraph のグラフ上でマウスホイール**:
  - **上スクロール**: カーソル位置を中心に X 軸ズームイン (= 20% per notch)
  - **下スクロール**: 同様にズームアウト
  - **Shift + ホイール**: Y 軸方向のズーム
  - **Ctrl + ホイール**: ブラウザのページズームに譲る (= 干渉なし)
  - inline / floating panel どちらでも動作

### Verification

- frontend vitest: **286 passed** (= 281 prior + 5 new wheel zoom)
- typecheck + production build: clean
- backend pytest: 1233 passed (回帰なし)

## [0.24.0] - 2026-05-11 — Scope 表示エリア + プロット設定 + floating panel

ADR-0044 採択。Scope の表示と操作性を大幅強化。**完全後方互換** (= 既存
`.flw.json` は無改変、schema 0.8 維持、`scope_settings` は optional フィールド)。

### Added

- **Canvas / Scope エリア drag resize**: `react-resizable-panels` の縦分割で
  両エリアの分割比をユーザー操作。分割比は localStorage 永続 (workspace 横断)。
- **per-Scope プロット設定 dialog**: ScopeView ヘッダの gear ボタンから開く:
  - **Y 軸**: auto / manual / log (= log で 0/負値があれば auto に fallback + 警告)
  - **X 軸**: auto / manual
  - **凡例位置**: top / bottom / right / off
  - **グリッド**: major / minor の on/off
  - **per-signal 線色 / 線幅**: `react-colorful` の color picker、1/2/3 px width
  - 設定は `editingModel.scope_settings[scopeId]` に保存 → File API で
    `.flw.json` に永続化 (= モデル単位、`git diff` で追跡可)
- **Scope ダブルクリック → floating panel**: Canvas で Scope / XYGraph
  ブロックをダブルクリック → `react-rnd` の drag + resize 可能な floating panel:
  - Stop 後も保持 (= scope buffer データを表示継続)
  - 複数 Scope 同時オープン (= z-index は最後にクリックした panel が前面)
  - モデル切替 / closeTab で全 panel 自動 close
  - panel 位置 / サイズは localStorage 永続
    (`pyflw.scope_panel.<workspace_hash>.<base64(model_path)>.<scope_id>`)
- **inline ScopeView ヘッダ**: gear / 最大化 / panel 化ボタン (= ダブルクリック
  以外の経路でも panel を開ける)
- **maximize ボタン** (= ScopeView ヘッダ): Scope エリア内で 1 個だけを全画面化、
  再押下で縦並びに戻る

### Changed

- ADR-0023 §Decision §(7) の「8 色 ローテーション固定」を **8 色 fallback +
  per-signal user override 可** に amend
- ADR-0023 §Decision §(8) bundle 予算: +15 KB → **+30 KB**
  (`react-resizable-panels` ~6 KB / `react-rnd` ~12 KB / `react-colorful` ~3 KB
  gzip)

### Migration

なし。完全後方互換。既存 Scope は `scope_settings` フィールドが無いだけで
今までと同じ uPlot 自動色 8 色 fallback で表示される。

### Out of Scope (= 永続的 / 別 ADR 送り)

- **物理的に別ウィンドウ (window.open + BroadcastChannel)**: stretch、必要性
  顕在化時に独立 ADR で起草
- **背景色 / ダークモード**: 永続的 out-of-scope (= memory `feedback_no_dark_mode`)

### Verification

- backend pytest: **1233 passed / 2 skipped** (= 既存テスト回帰なし)
- frontend vitest: **281 passed** (= 281 prior、回帰なし)
- typecheck + production build: clean

## [0.23.0] - 2026-05-11 — ワークスペース機能強化 (Recent / 複数タブ / 検索)

ADR-0043 採択。FileBrowser を起点に、日常使いに耐えるワークスペース UX を組む。
**完全後方互換** (= 既存 `.flw.json` は無改変、schema 0.8 維持)。詳細は ADR-0043
を参照。

### Added

- **前回 active file の自動復元**: 起動時に最後に開いていたファイルを
  workspace 単位で localStorage から復元 (`pyflw.last_active.<workspace_hash>`)
- **Recent Files メニュー**: File メニューに最近開いたファイル一覧を表示。
  上限 10 件、workspace 単位で別エントリ管理 (`pyflw.recent.<hash>`)、
  「履歴をクリア」アクション
- **複数ファイル同時編集 (multi-tab)**: TabStrip が N タブに対応。
  - クリックでタブ切替
  - middle-click でタブ閉じ
  - **Ctrl+Tab** / **Ctrl+Shift+Tab** で循環切替
  - 各タブが独立した ``editingModel`` / ``dirty`` / undo-redo 履歴を保持
  - rename はタブ追従、delete は active タブを閉じて隣接へ切替
- **検索 (Ctrl+P / Ctrl+Shift+F)**: VSCode 風 overlay panel:
  - **Ctrl+P**: ファイル名 fuzzy 検索 (rapidfuzz WRatio、score ≥ 50)
  - **Ctrl+Shift+F**: 内容 substring 検索 (case-insensitive、line-by-line)
  - workspace 直下の `.gitignore` を尊重 (= `pathspec`)
  - hard-coded 除外: `.git` / `.venv` / `__pycache__` / `node_modules` /
    `dist` / `build` / `.mypy_cache` / `.ruff_cache` / `.pytest_cache`
  - シンボリックリンクは辿らない (= 無限ループ防止)
  - 結果上限 100 件、超過時 truncated フラグ
- **新 backend endpoint**:
  - `GET /api/v1/files/workspace_info` → `{absolute_path, hash}` (hash =
    `sha256(absolute_path)[:16]`)、frontend が localStorage キー suffix に使用
  - `GET /api/v1/files/search?q=&kind=path|content&limit=` → 検索結果
- **新依存** (gui extras): `rapidfuzz>=3.6`、`pathspec>=0.12`

### Migration

なし。完全後方互換。既存利用者は何もしなくても新機能が利用可能。
`pyflw-server --workspace=PATH` の起動コマンドは変わらず。

### Verification

- backend pytest: **1233 passed / 2 skipped** (= 1219 prior + 14 new for
  workspace_info / search)
- frontend vitest: **281 passed** (regression なし)
- typecheck + production build: clean

## [0.22.0] - 2026-05-10 — Stop Time = `"inf"` (無限実行) + Scope ring buffer

ADR-0042 採択。Simulink 互換で Toolbar の Stop Time フィールドに `"inf"`
(case-insensitive) を入力すると、Stop ボタンを押すまで実行する unbounded run
を実現する。長時間実行で OOM しないよう Scope buffer はデフォルトで ring 化。
**完全後方互換** (= 既存 `.flw.json` は無改変で読める、schema 0.8 維持)。
詳細は ADR-0042 / ADR-0023 §Amendments を参照。

### Added

- **`Simulator(t_end="inf")` / `t_end=math.inf`** を受け入れ。``Simulator.run``
  はこのとき ``while True`` ループに切り替わり、停止は **Stop ボタン**
  (``request_stop()``) または ``on_step_callback`` が ``False`` を返したときのみ
- **`Scope.buffer_mode` パラメータ** (= `"ring"` default / `"bounded"` /
  `"unbounded"`) と `buffer_capacity` (default `100_000`):
  - `"ring"`: 最古サンプルから FIFO drop、無限実行で OOM 防止
  - `"bounded"`: 上限到達で `BufferOverflowWarning` を 1 回発し、以降は drop
    (= 初期サンプル保持)
  - `"unbounded"`: 上限なし。**`Simulator.t_end=inf` と組み合わせると build 時に
    `BlockSpecError` で reject** (= OOM 必至のため)
- **`pyflw.core.persistence.parse_t_end` / `serialize_t_end`** 関数 (public)
- **frontend Toolbar Stop Time** で `"inf"` を入力可能。`+inf` / `infinity` / `∞`
  は意図的に reject (= backend と完全一致)
- **frontend StatusBar / SimulationControls**: unbounded 実行時は progress bar を
  非表示にし、`実行中 t={current} (∞、停止ボタンで終了)` ラベルを表示
- **frontend `scopeBuffer.ts`**: `MAX_SAMPLES = 100_000` で ring 化 (`Float64Array`
  の `copyWithin` による in-place shift)
- **WS `progress` / REST `GET /api/v1/simulations/{id}` の `t_end` フィールド**:
  `number | "inf"` Union (= JS `JSON.stringify(Infinity)==="null"` の罠回避)

### Changed

- `Simulator.t_end` 型が `float` から `float | str` (受入) → 内部表現は `float`
  (= 有限値または `math.inf`) に正規化
- ``Simulator.save`` は `math.isinf(t_end)` のとき `"inf"` 文字列で永続化 (=
  RFC 8259 違反の `"Infinity"` を回避)
- ADR-0023 §Decision §(2) の「シミュレーション完了後の trim は見送る」前提を、
  ring buffer 動作で部分 amend (= 完了後でなく実行中に capacity 上限で drop)

### Migration

なし。既存 `.flw.json` (`"t_end": <number>`) は無改変で読める。schema は 0.8
のまま、`Simulator` API も追加のみで既存コード回帰なし。

### Verification

- backend pytest: **1219 passed / 2 skipped** (= 1187 prior + 32 new across
  `test_persistence_t_end.py`, `test_simulator_unbounded.py`,
  `test_scope_buffer_modes.py`, `TestUnboundedTEnd`)
- frontend vitest: **281 passed** (= 271 prior + 7 timeUtil + 3 ring tests)
- typecheck + production build: clean
- `examples/spring_mass_damper.py`: Final x=0.2505, x_dot=0.0031 (数値完全不変)

## [0.21.0] - 2026-05-10 — JupyterLab 流ローカルファイル直接編集 + legacy API 削除 (BREAKING)

ADR-0041 (JupyterLab 流ローカルファイル直接編集) の本格移行に伴う major
release。v2.x で並行サポートしていた legacy ``/api/v1/models/*`` REST と
``--model-dir`` CLI を **完全削除** し、frontend を ``selectedFilePath`` 一本化
した。詳細は ADR-0038 §Amendments §(3) / ADR-0041 §論点 4-A 参照。

### Breaking changes

- **REST `/api/v1/models/*` を全削除** — `POST/GET/PUT/DELETE/COPY` +
  `next-untitled` (= 7 endpoint)。利用者は `/api/v1/files/*` (= JupyterLab
  contents API 互換) に移行する。
- **`POST /api/v1/simulations` の `model_id` body を削除** — `model_path`
  (workspace 相対 path) または `model` (inline FlwModel dict) のみ受け付ける。
- **`pyflw-server --model-dir DIR` を削除**、**`--workspace DIR` を必須化** —
  workspace は path traversal 防御 (= `pyflw/server/security/paths.py`) を
  通したのち file 操作の root として使われる。
- **`Settings.model_dir` フィールドを削除**、`workspace_root: Path` が必須化。
- **frontend `selectedModelId` / `updateModel` / `startSimulation(model_id)` /
  `OpenModelDialog` / `RenameDialog` / `ConfirmDialog` を削除** —
  `selectedFilePath` のみが「選択中の編集対象」を表す。

### Migration

flat な model directory を保持していた利用者向けに **1 リリース限定** で
migration サブコマンドを提供する:

```bash
pyflw-server --migrate-models-to=./workspace --legacy-models-dir=./old_models
```

- `*.flw.json` を非破壊コピー (`shutil.copy2` で mtime 保持)
- 既存 path は skip、`--force` で上書き
- 結果は JSON report (`copied` / `skipped` / `errors`) で stdout 出力
- exit code: 0 = 全 OK / 1 = 一部 skip / 2 = エラーあり

migration 後は通常の `pyflw-server --workspace=./workspace` で起動する。

### Added

- `pyflw/server/security/paths.py` — `resolve_workspace_path` 7 step path
  traversal 防御 (= URL decode → control char 拒否 → 絶対 path 拒否 → `..`
  単体拒否 → `Path.resolve` → root containment check → Windows reserved name
  検証)
- `pyflw/server/migrations/__init__.py` — `migrate_models_to(src, dst, *,
  force=False) -> MigrationReport`
- `pyflw-server --migrate-models-to / --legacy-models-dir / --force` CLI

### Removed

- backend: `pyflw/server/routes/models.py`、`models_router` の include、
  `tests/server/test_models_api.py`
- frontend: `OpenModelDialog` / `RenameDialog` / `ConfirmDialog` (= Modal.tsx)、
  `modal.open.*` / `modal.rename.*` / `modal.button.rename` i18n keys
- frontend hooks: `useAutoSave` / `useSimulation` の legacy 経路分岐 (= 純粋に
  File API 経路のみ)

### Verification

- backend pytest: **1160 passed / 2 skipped** (= 既存 mypy --strict / ruff clean)
- frontend vitest: **271 passed** (= 既存テスト回帰なし)
- frontend typecheck + production build: clean
- `examples/spring_mass_damper.py`: Final x=0.2505, x_dot=0.0031 (= 数値完全不変)

### v0.20.12 → v0.21.0 移行手順

1. legacy `--model-dir DIR` で運用していた場合: `pyflw-server
   --migrate-models-to=./workspace --legacy-models-dir=./DIR` で workspace に
   コピー
2. 起動コマンドを `pyflw-server --workspace=./workspace` に置換
3. 自作 REST クライアントを使っていた場合: `/api/v1/models/*` の呼び出しを
   `/api/v1/files/*` 経路に置換 (= JupyterLab contents API 互換)
4. backend に直接依存していた場合: `Settings(workspace_root=Path("..."))` で
   構築、`create_app(settings=...)` の keyword 必須引数化

## [0.20.12] - 2026-05-10 — 矢印 head が node 境界に触れない問題を修正

ユーザー指摘 (= 「接続先の矢印とブロックが接地してないですね」) への対応。
v0.20.11 で ``TARGET_INSET_PX = 12 - 8 = 4`` と計算したが、SVG markerEnd の
描画方向を考慮していなかった。

### Root cause

SVG markerEnd は path 終端を **矢印先端の anchor** として描画し、矢印 base
は path 方向の **逆側** (= source 方向) に伸びる:

- 入力ポート (Left pos) の場合、path は左方向に進んで終わる → 矢印先端は
  adjustedTargetX、矢印 base は adjustedTargetX **+ 8 px** (= 右、外側)
- v0.20.11 の inset=4 だと adjustedTargetX = node 境界 - 8 px (= 外側) →
  矢印先端 = node 境界 - 8 px → node に届かない (= ユーザー指摘)

入力ポートの矢印 head は **node 外側に既に描画される** ため、target 側を
node 境界に揃える inset=12 でも矢印は node に重ならず、先端が node 境界
にぴったり触れる。

### Fixed

- ``BranchableEdge``: ``TARGET_INSET_PX`` (= 4) を削除、``adjustWithInset``
  も ``adjustToBorder`` に rename して inset 引数を撤去
- source / target ともに ``PORT_TO_NODE_BORDER_PX = 12`` で補正 → adjusted
  target = node 境界 → 矢印先端 = node 境界 → 矢印が node に綺麗に到達
- ``DiagramCanvas`` / ``defaultEdgeOptions.markerEnd`` は v0.20.11 のまま (=
  ``SIMULINK_MARKER_END``)

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean

### v0.20.11 → v0.20.12 移行

利用者は何もする必要なし。サーバ再起動で矢印先端が node 境界線に綺麗に触れる。

## [0.20.11] - 2026-05-10 — edge 終点の矢印 head を復活

ユーザー指摘 (= 「エッジの端の矢印が表示されなくなったので、それは復活して
もらえますか」) への対応。v0.20.10 で edge 起点を node 境界に揃える修正は奇麗
にハマったので、今度は **target 側の補正を矢印 head のサイズ分減らして** 矢印
を綺麗に描画する。

### Calculation

- ``PORT_TO_NODE_BORDER_PX = 12`` (= Handle width / 2)
- ``ARROW_HEAD_SIZE_PX = 8`` (= ``SIMULINK_MARKER_END.width``)
- ``TARGET_INSET_PX = 12 - 8 = 4``
- source 側補正: 12 px → edge 起点 = node 境界線
- target 側補正: 4 px → edge 終点 = node 境界 + 8 px 外側
  - React Flow markerEnd は edge 終点を矢印先端の anchor に取るので、矢印先端
    は node 境界 + 8 px、矢印 base は node 境界に綺麗に触れる位置 → 矢印 head
    全体が node 外側で path の方向を向いて node に入ってくる見た目

### Fixed

- ``BranchableEdge``: ``adjustToBorder`` を ``adjustWithInset`` に rename + 引数
  に ``inset`` を追加、source/target で異なる補正量を渡せるように
- ``BranchableEdge``: ``markerEnd`` prop を ``BaseEdge`` に渡すよう復活
- ``DiagramCanvas``: ``defaultEdgeOptions.markerEnd`` に ``SIMULINK_MARKER_END``
  を復活 (= ``ArrowClosed``、width=8、height=8、stroke 色)

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean

### v0.20.10 → v0.20.11 移行

利用者は何もする必要なし。サーバ再起動で edge の終端に矢印 head が綺麗に
描画される。

## [0.20.10] - 2026-05-10 — edge 起点を node 境界に (ポート位置は不変)

ユーザー指摘 (= 「ポート位置は動かさず、ポート接続後はエッジの起点をポートで
はなくてブロックにしてほしい」) への正しい対応。v0.20.8 でポート位置を動かして
失敗したので、今度は **edge の描画座標だけ** を補正する。

### Approach

React Flow は ``BranchableEdge`` (Custom Edge) の props として ``sourceX/Y``
``targetX/Y`` に **Handle center 座標** (= node 境界の +12 px 外側、Handle
width=24 のため) を渡してくる。これを **Position に応じて 12 px 内側にずらして**
``getSmoothStepPath`` に渡すと、edge path が node 境界に当たる見た目になる。

- chevron (= node 境界の +12 px 外側) は **不変**
- Handle (= 24×24 hit area) も **不変**
- edge の描画座標だけ 12 px 内側

### Fixed

- ``BranchableEdge`` に ``adjustToBorder(x, y, position)`` ヘルパ追加 (=
  ``Position.Right`` なら ``-12 px``、``Position.Left`` なら ``+12 px``、
  ``Top/Bottom`` も同様)
- ``sourceX/Y`` / ``targetX/Y`` を補正してから ``getSmoothStepPath`` を呼ぶ
- ``PORT_TO_NODE_BORDER_PX`` 定数 (= 12 px = Handle width / 2) を導入

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean

### v0.20.9 → v0.20.10 移行

利用者は何もする必要なし。サーバ再起動で edge が node 境界に直接当たる見た目
になり、chevron / Handle 位置は v0.20.7-v0.20.9 と同じ。

## [0.20.9] - 2026-05-10 — v0.20.8 撤回 (ポート位置を元に戻す)

ユーザー指摘 (= 「ポート位置を変更するなって言ってんだろ」) への対応。
v0.20.8 で Handle center を node 境界にロックする ``transform`` override を
入れたが、結果として **Handle が node 内側 24 px に押し込まれて chevron が
ブロック内に表示される** 問題が発生していた (= React Flow Handle のデフォルト
position 計算と私の transform override が衝突)。

### Reverted

- ``arrowHandleStyle`` の ``transform`` override を撤回 → React Flow デフォルト
  に戻す
- chevron 位置 / Handle 配置は v0.20.4-v0.20.7 と完全に同じに復元

### 既知の trade-off

- edge と node の隙間 ~12 px (= React Flow デフォルト Handle の center が
  node 境界の少し外側にある) は v0.20.7 markerEnd 削除分のみで折り合う
- 完全に隙間ゼロにするには Handle 配置 / chevron 配置を別アプローチで再設計
  する必要あり (= 別途検討、ポート位置を壊さない設計を優先)

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean

### v0.20.8 → v0.20.9 移行

利用者は何もする必要なし。サーバ再起動でポート位置が v0.20.7 と同じに戻る。

## [0.20.8] - 2026-05-10 — edge と block の隙間を完全解消 (Handle transform override)

v0.20.7 で markerEnd を削除したが、まだ ~12 px の隙間が残るというユーザー指摘
への追加対応。根本原因は v0.20.4 で Handle を 24×24 に拡大した際、React Flow
の **デフォルト transform が Handle を node の完全外側に押し出す** ため Handle
center (= edge anchor) が node 境界の +12 px 外側になっていた。

### Fixed

- ``arrowHandleStyle`` に ``position: Position`` 引数を追加し、``transform`` を
  override:
  - ``Position.Right``: ``translate(-50%, -50%)`` で Handle center を node 右辺に
    ロック
  - ``Position.Left``: ``translate(50%, -50%)`` で Handle center を node 左辺に
    ロック
- これにより Handle の半分 (= 12 px) は node 内側に重なるが、edge anchor は
  node 境界線にぴったり一致 → 隙間ゼロ
- node 端 (= port エリア) でクリックすると connection drag を開始するのは
  Simulink でも同じ慣習なので問題なし

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean
- ``examples/spring_mass_damper.py`` 数値完全不変

### v0.20.7 → v0.20.8 移行

利用者は何もする必要なし。サーバ再起動で自動反映。

## [0.20.7] - 2026-05-10 — edge と block の隙間を解消 (markerEnd 削除)

ユーザー指摘 (= 「ブロックとエッジの隙間が大きい、接続してしまえばエッジの
表示の起点はブロックからでいい」) への対応。

### Changed

- **接続済み edge の ``markerEnd`` (= 矢印 head) を削除**:
  - React Flow は矢印 head を node 境界の外側に描画するオフセットを自動的に
    入れるため、edge の終端が node から ~10 px 離れて見えていた
  - Simulink でも接続済み配線は純粋な線で、信号方向は node 配置 (= 左→右)
    で把握する慣習
  - これにより edge は node 境界に直接到達する見た目に
- **`defaultEdgeOptions.markerEnd`** を削除、**`BranchableEdge`** も markerEnd
  prop を渡さない
- ``SIMULINK_MARKER_END`` 定数自体は ``diagramConverter.ts`` に残す (= 将来
  drag connection 中の仮 edge で再利用する余地、現状未使用)

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし)
- TypeScript strict mode clean
- production build clean (= 196 KB gzip 帯維持)
- ``examples/spring_mass_damper.py`` 数値完全不変

### v0.20.6 → v0.20.7 移行

利用者は何もする必要なし。サーバ再起動で自動反映。

## [0.20.6] - 2026-05-10 — Simulink 流ドラッグ&ドロップで配線から分岐

ユーザー指摘 (= 「エッジの任意の点をクリックしてそのままドラッグアンドドロップで
ほかのブロックに接続できるようにしてほしい、Simulink と同じ振る舞いに」) への
対応。v0.20.5 では Ctrl+クリック方式しか提供しておらず Simulink 互換ではなかった。

### Added

- **Simulink 流のドラッグ分岐配線** (= 既存配線をクリック → そのまま drag →
  別ブロックに drop で枝分かれ edge を追加):
  - **Custom Edge ``BranchableEdge``** 新規: React Flow built-in ``"step"``
    edge と同じ見た目 (= 直角ステップ折れ線 + 矢印 head) を ``getSmoothStepPath``
    で再現しつつ、上に **invisible で太い (= 20px) overlay path** を重ねて
    ``onPointerDown`` を捕捉、cursor は crosshair
  - **DiagramCanvas に branch drag state + window pointer handler**:
    - mousedown で edge 起点を記録 (= src + src_idx)
    - mousemove でカーソル位置追跡、画面全体に SVG overlay で破線追従線描画
    - mouseup で ``document.elementFromPoint`` → ``data-id`` を持つ React Flow
      ノードを探索 → input port[0] (= dst_idx=0) に edge 追加
    - **ESC キー** または ブロック以外で離す → cancel
- ``SIMULINK_EDGE_TYPE`` を built-in ``"step"`` から custom ``"branchable"`` に
  変更 (見た目は不変)
- Help > Keyboard shortcuts ダイアログ ``Connection`` セクションに「Drag from
  edge → Drop on block」エントリを追加 (= 主要 UX として宣伝)
- i18n key 1 件追加 (en/ja): ``modal.shortcuts.desc.drag_branch``

### 利用例 (= Display ブロックを既存配線につなぐ、Simulink 流儀)

1. キャンバスに ``Constant → Gain → Integrator`` を配置 + 配線済
2. キャンバス側方の Display ブロックを drag-drop で配置
3. **``Gain → Integrator`` の配線上の任意点をクリック → そのままドラッグ →
   Display にドロップ** → ``Gain → Display`` の分岐配線が成立 (Simulink 互換)

v0.20.5 の Ctrl+クリック方式も併存 (= 利用者が好きな方を使える)。

### Internal / Tests

- vitest **272 件 pass** (= 既存テスト回帰なし、ドラッグ分岐は手動検証)
- TypeScript strict mode clean
- production build clean (= 196 KB gzip 帯維持)
- ``examples/spring_mass_damper.py`` 数値完全不変

### v0.20.5 → v0.20.6 移行

利用者は何もする必要なし。サーバ再起動で自動反映。

## [0.20.5] - 2026-05-10 — 既存配線から分岐 (= Branch wire from edge)

ユーザー指摘 (= 「Display ブロックなどをエッジに接続する機能が入っていない、
わざわざブロックの根本から接続しろというのか」) への対応。v0.20.4 ではポート
hit area 拡大で「ブロック起点の drag connection」改善のみで、Simulink 流の
**既存配線から分岐**機能は実装していなかった。

### Added

- **既存配線から分岐配線を引く機能** (= 既存の 2-step Ctrl+クリック auto-
  connect を edge 起点に拡張):
  - **Ctrl+Click edge → Ctrl+Click block**: 既存 edge の src + src_idx を 1
    回目選択として記録、次のブロック Ctrl+Click で ``edge.src → block.in[0]``
    の枝分かれ edge を追加
  - 視覚フィードバック: edge が Ctrl+Click で選択状態になる (= 1 回目を選んだ
    ことが分かる)
  - 同じノード自身を 2 回 Ctrl+Click すると cancel
- **``onEdgeClick``** ハンドラを ``DiagramCanvas`` に新規追加 (= 通常クリックで
  auto-connect 中断、Ctrl+クリックで分岐モード開始)
- **``autoConnectSource``** state を ``string | { src; src_idx } | null`` に
  拡張 (= ノード単独 / edge 由来の両モード保持)
- **Help > Keyboard shortcuts** ダイアログに新セクション ``Connection`` 追加
  (= auto_connect / branch_connect の 2 行で利用方法を案内)
- i18n keys 4 件追加 (en/ja): ``modal.shortcuts.section.connect`` /
  ``.desc.auto_connect`` / ``.desc.branch_connect``

### 利用例

シンク系ブロック (Display / Scope) を既存配線につなぐとき:
1. ``Constant → Gain → Integrator`` の信号線 (例えば Gain → Integrator の edge)
   を **Ctrl+Click**
2. キャンバスに新規 Display ブロックを置いて **Ctrl+Click**
3. → ``Gain → Integrator`` と並んで ``Gain → Display`` の分岐配線が成立

### Internal / Tests

- vitest **272 件 pass** (= 既存テストに回帰なし、分岐接続は手動検証のみ)
- TypeScript strict mode clean
- production build clean (= 196 KB gzip 帯維持)
- ``examples/spring_mass_damper.py`` 数値完全不変

### v0.20.4 → v0.20.5 移行

利用者は何もする必要なし。サーバ再起動で自動反映。

## [0.20.4] - 2026-05-10 — Workspace 折りたたみ + ポート hit area 拡大

ユーザーフィードバック 3 件への対応:

1. ワークスペースを折りたためるようにしてください
2. 出力ポートの ``>`` の部分には当たり判定がなく、カーソルがクロスにならない
3. Display ブロックなど、エッジから接続したいのにできない

### Added

- **Workspace パネル折りたたみ** (= ADR-0041 §論点 7-A 補強):
  - FileBrowser header 全体クリックで tree を折りたたみ / 展開、状態は
    localStorage (``pyflw.workspace_collapsed``) に永続化
  - 折りたたみ時は左サイドバーの上半分が **24px header のみ** になり、
    Library palette がほぼ全面表示される (= ブロック追加に集中したい時の UX 改善)
  - ▸ / ▾ アイコンと aria-expanded 属性で状態を視覚化 + a11y 対応
  - i18n key 2 件追加 (``filebrowser.collapse`` / ``.expand``)

### Fixed

- **ポート Handle の hit area 不足** (= ``arrowHandleStyle`` 12×12 → 24×24):
  - chevron ``>`` (= Handle 中心から外側 +6〜+12 px の位置に表示) が hit area
    の外で、カーソルを乗せても connect cursor (= ``cursor: crosshair``) が
    効かなかった bug。Handle サイズを 24×24 に拡大して chevron を完全に hit
    area 内に含める
  - 副次効果: Display 等の入力ポートに対する drag connection (= 他ブロック
    から線を引いて drop) も chevron 上で drop 成立するため、これまで「接続
    できない」場面が解消
  - Handle 中心位置 (= ブロック境界線上) は不変 → edge anchor 位置 / 視覚的
    な配線終端は変化なし

### Internal / Tests

- vitest **272 件 pass** (回帰なし)
- TypeScript strict mode clean
- production build clean (= 196 KB gzip 帯維持)
- ``examples/spring_mass_damper.py`` 数値完全不変

### v0.20.3 → v0.20.4 移行

利用者は何もする必要なし。サーバ再起動すれば自動反映。

## [0.20.3] - 2026-05-10 — i18n hotfix: Help / FileBrowser / 各 modal の翻訳追加

ユーザー指摘 (= 「ヘルプの内容が、言語設定が反映されていない」) への hotfix。
v0.19.0 / v0.20.0 で追加した dialog 群と FileBrowser context menu / Help menu の
文字列は辞書登録されておらず、``defaultValue`` のみ指定だったため日本語に
切り替えても英語のまま表示されていた bug。

### Fixed

- ``en.json`` / ``ja.json`` に **50+ keys 追加**:
  - **Help menu**: ``menu.help.about`` / ``.documentation`` / ``.shortcuts``
  - **AboutDialog**: ``modal.about.title`` / ``.description`` / ``.license``
  - **KeyboardShortcutsDialog**:
    - section 4 件 (= file / edit / navigation / simulation)
    - description 16 件 (= undo / redo / cut / copy / paste / select_all /
      delete / new_file / open / save / save_as / drill_in / drill_up /
      rename_file / run / stop)
  - **SaveAsPathDialog**: ``modal.save_as.title`` / ``.label`` / ``.invalid`` /
    ``.conflict`` / ``.overwrite_confirm``
  - **DirtyConfirmDialog**: ``modal.dirty_confirm.title`` / ``.message`` /
    ``.discard`` / ``.save_and_open``
  - **FileBrowser**: ``filebrowser.title`` / ``.refresh`` / ``.disabled`` /
    ``.loading`` / ``.empty`` / ``.confirm_delete`` / ``.confirm_discard`` /
    ``.prompt_new_file`` / ``.prompt_new_folder`` / ``.prompt_save_as`` /
    ``.menu.new_file`` / ``.menu.new_folder`` / ``.menu.rename`` / ``.menu.delete``
  - **modal.button.close** (= 共通)
- ``KeyboardShortcutsDialog`` の ``description`` を hardcoded 英語から i18n
  key 経由に変更

### v0.20.2 → v0.20.3 移行

利用者は何もする必要なし。ja 設定で開いた時に Help メニュー / 各 dialog が
正しく日本語表示されるようになる。

## [0.20.2] - 2026-05-10 — Edit メニュー削除 (UI cleanup)

ユーザー指摘 (= 「編集の内容は、わざわざこのようなメニューで用意するほどの
ことでしょうか」) に応えた patch リリース。v0.20.0 で追加した Edit メニューは
全項目がキーボードショートカットでアクセス可能 + Toolbar に Undo/Redo ボタン
あり + pyflw 固有の編集機能 (Find / Auto-arrange 等) もまだ無い → メニュー
として価値が低かった。

### Removed

- **MenuBar の Edit メニュー** (= File / View / Simulation / Help の 4 項目に)
  - Undo / Redo は Toolbar / Ctrl+Z / Ctrl+Shift+Z で操作
  - Cut / Copy / Paste は Ctrl+X / C / V で操作
  - Select All は Ctrl+A、Delete は Del キーで操作
  - 一覧は Help > Keyboard shortcuts ダイアログで参照可能 (= 残置)

### 設計判断

- pyflw 固有の編集機能 (Find / Replace / Comment / Auto-arrange) が将来追加
  されたタイミングで Edit メニューを再導入する予定。それまでは「項目あるべき」
  感を捨ててシンプルさ優先

### Internal

- vitest **272 件 pass** (= 既存テストに影響なし)
- TypeScript strict mode clean、bundle 軽量化 (= ~0.3 KB 減)

### v0.20.1 → v0.20.2 移行

利用者は何もする必要なし (= キーボードショートカットは全て継続動作)。

## [0.20.1] - 2026-05-10 — undo/redo 履歴粒度を粗くする hotfix

ユーザー指摘 (= 「ブロック移動の履歴の粒度が細かい」) に応えた patch リリース。
v0.20.0 の Undo / Redo は ``applyEditingModel`` 呼び出しごとに履歴 push するため、
React Flow が 1px ずつ ``onNodesChange`` を発火する**ブロックドラッグで履歴が
即座に 50 件埋まる** 問題があった。Ctrl+Z 1 回で 1px しか戻らず実用的でない。

### Fixed

- **``applyEditingModel(fn, options)`` に ``mergeKey`` を追加**: 直前と同じ
  ``mergeKey`` の連続呼び出しは history に追加 push せず、editingModel だけ
  更新する (= 最初の 1 entry だけ残る)。別 ``mergeKey`` または ``undefined``
  で「新しい操作」と判定して新規 push
- **連続呼び出し系 action に mergeKey 指定**:
  - ``updateBlockPosition`` → ``move:{id}`` (1 ブロックドラッグ)
  - ``updateBlockPositions`` → ``move-multi:{ids}`` (複数選択ドラッグ、ID 集合
    が同じ間は merge)
  - ``updateBlockSize`` → ``resize:{id}`` (NodeResizer ドラッグ)
  - ``updateSimulatorConfig`` → ``sim-config:{fields}`` (= Toolbar StopTime
    number input typing)
  - ``updateBlockParams`` → ``params:{id}`` (= ParameterPanel 連続編集)
  - ``updateSubsystemMaskValues`` → ``mask:{id}``
- **undo / redo 後は ``lastMergeKey = null``**: 巻き戻し直後の編集は merge せず
  必ず新規 entry (= 利用者が undo してから別操作を始める想定の自然な挙動)
- **``setEditingModel`` / ``selectFilePath`` / ``selectModel`` で
  ``lastMergeKey`` クリア**: ファイル切替後の最初の編集は新規 entry に

### Internal / Tests

- vitest **+5 件追加** (= ``undoRedo.test.ts`` の merge セクション、合計
  **272 件 pass**):
  - 同一 mergeKey の連続 → 1 entry のみ
  - 別 mergeKey で別 entry
  - mergeKey なしは従来通り常に新規 entry
  - ドラッグ後 Ctrl+Z 1 回で操作前に戻る
  - undo / redo 後は merge をリセット
- TypeScript strict mode clean、bundle gzip 帯維持

### v0.20.0 → v0.20.1 移行

利用者は何もする必要なし (= API 変更なし、純粋な UX 改善)。

## [0.20.0] - 2026-05-10 — Undo / Redo + Edit / Help メニュー (UX ポリッシュ)

ユーザーフィードバック (= 「Undo / Redo が機能していない」「Edit メニュー / Help
メニューが空」) に応えて、エディタの基本機能を補強する minor リリース。
ADR-0041 とは独立した GUI ポリッシュ。

**v0.20.0 は後方互換 minor**。

### Added

- **Undo / Redo** (= ``appStore`` に history stack):
  - ``editingModel`` に対する全ての ``applyEditingModel`` 呼び出しが
    過去状態を ``history.past`` に push、最大 50 件まで保持
    (``HISTORY_MAX``、超過分は古い順から drop)
  - ``undo()`` / ``redo()`` action、``canUndo()`` / ``canRedo()`` selector
  - ``setEditingModel`` (= ファイル load) / ``selectFilePath`` /
    ``selectModel`` で history を完全クリア (= 別ファイルと混ぜない)
  - undo / redo は ``dirty=true`` 化 (= 次回 auto-save で書き出す)
- **キーボードショートカット**:
  - ``Ctrl+Z`` / ``Cmd+Z`` → Undo
  - ``Ctrl+Shift+Z`` / ``Ctrl+Y`` → Redo
  - ``Ctrl+X`` → Cut (= Copy + Delete)
  - text input フォーカス中はブラウザネイティブ動作を優先 (= 既存規約踏襲)
- **Toolbar の Undo / Redo ボタンを有効化** (= v0.19.0 まで disabled プレース
  ホルダだった)
- **Edit メニュー** (= 既存ショートカットを menu からも呼べるように):
  - Undo / Redo / Cut / Copy / Paste / Select All / Delete
  - 選択なし / 履歴なしでは disable
- **Help メニュー**:
  - **About pyflw**: バージョン / GitHub link / MIT license を表示する
    ``AboutDialog`` モーダル
  - **Documentation**: GitHub repo を新タブで開く
  - **Keyboard shortcuts**: 主要ショートカット一覧モーダル
    (``KeyboardShortcutsDialog``、4 セクション × 計 14 項目)

### Internal / Tests

- vitest **+12 件追加** (= ``undoRedo.test.ts``、history push / undo round trip /
  HISTORY_MAX 上限 / 別ファイル切替時の clear 等)、**合計 267 件 pass**
- TypeScript strict mode clean、bundle gzip 帯維持
- ``examples/spring_mass_damper.py`` 数値完全不変 (Final x=0.2505, x_dot=0.0031)

### 設計判断

- **history は ``editingModel`` 全体を deep-clone**: action-based より単純で
  ``undo``/``redo`` のロジックがほぼ trivial。50 件 × 平均 100 KB ≒ 5 MB の
  メモリ目安、現実的な範囲
- **``setEditingModel`` で history clear**: 別ファイルの過去状態を持ち越すと
  混乱の元 (= ``selectFilePath`` / ``selectModel`` も同様にクリア)
- **input focus 中の Ctrl+Z**: 既存の ``isTextEditing(target)`` で skip、テキスト
  入力中はブラウザ任せ
- **``AboutDialog`` / ``KeyboardShortcutsDialog``**: 軽量実装で外部依存追加なし、
  ``ModalShell`` 既存 component を再利用

## [0.19.0] - 2026-05-10 — 外部編集検知 + 本格モーダル (ADR-0041 §論点 9-A / 10-A / 11-A)

ADR-0041 frontend 段階の **part 3 (= 残作業 closure)**。外部エディタとの併用を
支える polling 機構と、``window.prompt`` / ``window.confirm`` を本格モーダル
に置換。

**v0.19.0 は後方互換 minor**。

### Added

- **``useExternalChangesPoll``** (= ADR-0041 §論点 11-A):
  - ``selectedFilePath`` が non-null + シミュレーション実行中でない時、5 秒
    間隔で ``GET /api/v1/files/content`` を polling
  - etag が一致 → no-op (= 変更なし)
  - etag 不一致 + ``dirty == false`` → silent reload (= editingModel を新内容
    で上書き)
  - etag 不一致 + ``dirty == true`` → ``window.confirm`` で 「外部変更を取り
    込む / 自分の変更を残す」 を選択 (本格モーダルは v0.20.0 で別途実装可)
  - JupyterLab 既定と整合 (= 5 秒間隔)、OS 別 file watcher は採用しない
- **``SaveAsPathDialog``** (= ADR-0041 §論点 10-A 本格版):
  - ``Modal.tsx`` に追加、``ModalShell`` ベース
  - workspace 相対 path 入力 (POSIX 形式)、autofocus 時に拡張子前 stem を選択
  - 不正文字 (= backslash / 制御文字 / 先頭 ``/``) を入力時に警告
  - 既存 path との衝突は warning 表示 + submit 時に上書き confirm
  - ``window.prompt`` を置換 (= MenuBar.Save As)
- **``DirtyConfirmDialog``** (= ADR-0041 §論点 9-A 3-button モーダル):
  - 3 ボタン: Cancel / **Discard changes** (= rose) / **Save & Open** (= blue)
  - FileBrowser の dirty 状態でファイル切替時に発火 (``window.confirm`` 置換)
  - "Save & Open" ボタンは現在ファイルを保存してから新ファイルを開く一連の動作

### Changed

- **MenuBar.Save As** が ``SaveAsPathDialog`` 経由に (= ``window.prompt`` 撤去)
- **FileBrowser のファイル切替時の dirty 確認** が ``DirtyConfirmDialog``
  経由に (= ``window.confirm`` 撤去)
- **App.tsx** が ``useExternalChangesPoll`` を mount

### Internal / Tests

- vitest **+10 件追加** (= context menu 3 件、dirty modal 1 件、external poll
  6 件)、**合計 255 件 pass**
- TypeScript strict mode clean、bundle gzip 帯維持
- ``examples/spring_mass_damper.py`` 数値完全不変 (Final x=0.2505, x_dot=0.0031)

### v0.20.0 送り (= ADR-0041 §論点 7-A / 11-A 残作業)

- ``ExternalChangeModal`` (= ``useExternalChangesPoll`` の ``window.confirm``
  を 3-button モーダル化、Reload / Force overwrite / Cancel)
- ``OpenModelDialog`` 相当の File API 版 (= MenuBar の Open メニューが File
  API モードで FileBrowser tree を mini-dialog として表示)
- drag-drop でフォルダ移動 (`@dnd-kit` 既存依存を再利用、ADR-0019)
- 全ファイル表示 toggle / multi-select (Shift / Ctrl)
- inline rename の vitest (= 現状 useExternalChangesPoll / context menu /
  dirty modal までカバー、inline rename は手動検証のみ)

## [0.18.0] - 2026-05-10 — FileBrowser context menu + Simulation 実行対応 (ADR-0041 §論点 5-A / 7-A / 9-A / 10-A)

v0.17.0 で導入した FileBrowser サイドバーに **実用的な操作系を追加**。
File API モードでも **シミュレーション実行が可能** に (= 最重要、v0.17.0 では
Simulation Controls が非表示だった)。

**v0.18.0 は後方互換 minor**。

### Added

- **FileBrowser 右クリック context menu** (= ADR-0041 §論点 7-A):
  - `New file` / `New folder` (= 親ディレクトリ配下に作成)
  - `Rename (F2)` (= ファイルのみ、ディレクトリは disable)
  - `Delete` (= confirm 後、開いているファイルなら自動 close)
  - root 領域の右クリックで New file / New folder のみ表示
- **FileBrowser inline rename (F2)**: 選択中ファイルで F2 押下 → input が
  オーバーレイ表示、Enter で確定 / Escape でキャンセル / blur でも確定。
  拡張子前 (= stem 部分) を自動選択 (= JupyterLab 流儀)
- **dirty 確認ダイアログ** (= ADR-0041 §論点 9-A): 別ファイルを開く時に
  ``dirty == true`` なら ``window.confirm`` で破棄確認 (専用モーダルは
  v0.19.0 で実装、簡易版)
- **`MenuBar.New`** (= File API モード): `nextUntitledFilePath` で
  ``untitled<N>.flw.json`` を採番、空モデル雛形を File API で書き込んで開く。
  workspace 未有効 (= 503) なら legacy ``createModel`` に fallback
- **`MenuBar.Save As`** (= File API モード、簡易版): ``window.prompt`` で
  workspace 相対 path 入力、`putFileContent` で書き込み + 切替。本格モーダル
  は v0.19.0 (= ADR-0041 §論点 10-A FileBrowser 込み mini-dialog)
- **`MenuBar.Delete`** (= File API モード): confirm + ``deleteFile`` +
  selectFilePath(null)
- **`startSimulationByPath`** / **`startSimulationInline`** (= ``api/client.ts``
  追加、ADR-0041 §論点 5-A の 3 形式 body 用 client wrapper)

### Changed

- **`useSimulation.run()`** (= ADR-0041 §論点 5-A): ``selectedFilePath`` セット
  時は File API 経路 (= ``putFileContent`` で保存 → ``startSimulationByPath``
  で実行)、それ以外は legacy ``selectedModelId`` 経路。両モードで自動保存
  + 楽観ロック (= etag) を維持
- **`Toolbar.saveMutation`**: File API モード時は `putFileContent` で書き込み
  (= etag 楽観ロック対応)、legacy モード時は `updateModel`
- **`SimulationControls`** が **両モードで表示** (= v0.17.0 では File API
  モードで非表示だった)。``App.tsx`` の条件分岐を撤去
- **`MenuBar` File メニュー disable 状態**: New / Save / Save As / Close /
  Delete を `hasModel` (= 両モード) ベース、Rename のみ legacy 限定
  (= File API モードの rename は FileBrowser 経由で行うため)

### Internal / Tests

- vitest **245 件 pass** (= 既存テストに回帰なし、v0.19.0 で FileBrowser context
  menu / inline rename / Save As の追加テストを予定)
- TypeScript strict mode clean、bundle 192 KB gzip 帯維持
- ``examples/spring_mass_damper.py`` 数値完全不変 (Final x=0.2505, x_dot=0.0031)

### v0.19.0 送り (= ADR-0041 §論点 7-A / 9 / 10 / 11 残作業)

- ``SaveAsModal`` (= FileBrowser 込み mini-dialog、ADR-0041 §論点 10-A)
- ``DirtyConfirmModal`` (= window.confirm を本格モーダル化、ADR-0041 §論点 9-A)
- ``useExternalChangesPoll`` (= 5 秒 mtime/etag polling、ADR-0041 §論点 11-A)
- drag-drop でフォルダ移動
- 全ファイル表示 toggle / multi-select (Shift / Ctrl)
- FileBrowser context menu / inline rename の vitest 整備

## [0.17.0] - 2026-05-10 — FileBrowser サイドバー (ADR-0041 §論点 7-A / 8-A)

SPEC-0001 Phase 6+ #55 「ローカルファイル直接編集」の **frontend 段階 part 1**。
v0.16.0 で導入した backend File API を前提に、左サイドバーに **JupyterLab 流儀
の workspace ツリービュー** を新設し、ユーザーが ``.flw.json`` ファイルを直接
ブラウズしてクリック 1 つで開けるようにした。

**v0.17.0 は後方互換 minor**: 既存 endpoint 削除なし、Public API 凍結
(ADR-0038) を破壊せず、UI は既存 legacy フロー (``selectedModelId``) と
新 file path フロー (``selectedFilePath``) を **1 セッション 1 経路の相互排他**
で coexist。

### Added

- **左サイドバー上部に ``FileBrowser`` コンポーネント** (= ADR-0041 §論点 7-A、
  自前実装):
  - workspace tree 表示 (1 階層ずつ展開、React Query で TanStack キャッシュ)
  - ``.flw.json`` クリックで File API GET → ``editingModel`` に load
  - その他のファイル (= ``.flwlib.json`` 等) は disabled 表示
  - Refresh ボタン
  - 503 (= legacy ``--model-dir`` モード) なら「File API 無効」案内表示
- **state 拡張** (``appStore.ts``、ADR-0041 §論点 8-A):
  - ``selectedFilePath: string | null`` (= workspace 相対 POSIX path)
  - ``editingFileMtime`` / ``editingFileEtag`` (= 楽観ロック用)
  - ``selectFilePath(path)`` action (= legacy ``selectedModelId`` を nullify
    して 1 セッション 1 経路を強制)
- **File API client wrapper** ``api/filesApi.ts`` (= ``fileTree`` /
  ``getFileContent`` / ``putFileContent`` / ``renameFile`` / ``deleteFile`` /
  ``mkdir`` / ``nextUntitledFilePath``、``FileApiUnavailableError`` /
  ``EtagMismatchError`` の専用例外型付き)

### Changed

- **``useAutoSave``** が ``selectedFilePath`` セット時は File API
  (``PUT /api/v1/files/content`` + etag 楽観ロック) で保存、それ以外は
  legacy ``PUT /api/v1/models/{id}``。``Ctrl+S`` も同経路で flush
- **``StatusBar``** / **``TabStrip``** / **``MenuBar`` Close** が
  ``selectedFilePath`` 表示と Close 連動を実装。``TabStrip`` は basename
  (= ``path.split("/").pop()``) を主表示、フルパスを ``title`` で hover 表示
- **``DiagramCanvas``** の ``modelId`` prop を nullable 化 (= File API モード
  で ``null`` を渡すと legacy query を skip、``editingModel`` を直接利用)
- **``App.tsx``** 左サイドバーを 2 段組 (上 ``FileBrowser`` 40% / 下
  ``BlockPalette`` 60%) に再構成

### Internal / Tests

- **vitest +6 件** (= ``tests/fileBrowser.test.tsx``、tree rendering / file open
  click / non-flw filter / 合計 **245 件 pass**)
- TypeScript strict mode clean、bundle 192.18 KB gzip (= ADR-0023 1 MB 予算の
  19.2%)

### v0.18.0 送り (= ADR-0041 §論点 7-A / 8 / 9 / 10 / 11 段階移行)

- 右クリック context menu (Rename / Duplicate / Delete / New file / New folder)
- inline rename (F2)
- drag-drop でフォルダ移動
- 全ファイル表示 toggle (現状は tree で全ファイル列挙、有効フィルタは未実装)
- ``SaveAsModal`` / ``DirtyConfirmModal``
- ``useExternalChangesPoll`` (= 5 秒 mtime/etag polling、ADR-0041 §論点 11-A)
- ``MenuBar`` の File メニュー全面移行 (= New file in workspace、Save As path
  指定モーダル)
- ``useSimulation`` を ``model_path`` body 拡張 (= 現状 legacy ``model_id``
  経路でしか実行不可、File API モードでは Simulation Controls が非表示)

## [0.16.0] - 2026-05-10 — File API + ワークスペース対応 (ADR-0041 §1〜§5)

SPEC-0001 Phase 6+ #55 「ローカルファイル直接編集 (JupyterLab 流儀)」の **backend
段階** を ADR-0041 §論点 1〜5 に基づき実装。frontend FileBrowser
(= ADR-0041 §論点 7-A) は次の minor リリース、`/api/v1/models/*` 削除と
``--model-dir`` 削除は v3.0 (= ADR-0041 §論点 4-A、§論点 12-A 段階移行)。

**v0.16.0 は後方互換 minor**: 既存 endpoint 削除なし、Public API 凍結
(ADR-0038) を破壊せず、新 endpoint 追加 + deprecation 予告のみ。`pyflw-server`
の既定 workspace は **CWD** に変更 (= JupyterLab 既定と整合)。

### Added

- **REST File API** (`/api/v1/files/*`、6 endpoint、ADR-0041 §論点 1-A、
  JupyterLab `jupyter_server.contents` 互換):
  - `GET /api/v1/files/tree?path=<rel>` ディレクトリ列挙 (1 階層)
  - `GET /api/v1/files/content?path=<rel>` parsed JSON 内容 + mtime + etag
  - `PUT /api/v1/files/content?path=<rel>` 書き込み (etag 楽観ロック対応)
  - `POST /api/v1/files/rename` body `{from, to}` でリネーム / 移動
  - `DELETE /api/v1/files?path=<rel>` ファイル / 空ディレクトリ削除
  - `POST /api/v1/files/mkdir?path=<rel>` ディレクトリ作成 (`mkdir -p`)
- **CLI `--workspace=PATH`** 引数 (= File API のルートディレクトリ、default は
  `Path.cwd()`、ADR-0041 §論点 3-A)
- **`POST /api/v1/simulations`** で 3 形式 body 対応 (ADR-0041 §論点 5-A):
  - `{"model_id": str}` (= legacy、deprecated、後述)
  - `{"model_path": str}` (= workspace 相対 path)
  - `{"model": dict}` (= インライン dict、未保存 editingModel の試行実行)
- **Path traversal 防御モジュール** `pyflw.server.security.resolve_workspace_path`
  (= 7 step 検証、ADR-0041 §論点 2-A): null byte / control char / backslash /
  絶対 path / Windows ドライブ / `..` 単体 / Windows 予約名 (CON/PRN/AUX/NUL/
  COM0-9/LPT0-9) / trailing space-dot / containment escape を集中検証
- **`Simulator.from_dict(data)`** public API (= JSON dict から Simulator 構築、
  インライン実行で利用、ADR-0041 §論点 5-A)。`Simulator.load(path)` は
  `from_dict` 呼び出しに簡素化
- **`Settings.workspace_root: Path | None`** field (= File API の有効化判定)

### Deprecated

- **`/api/v1/models/*` 5 endpoint** (= ADR-0041 §論点 4-A): 全 response に RFC
  8594 `Deprecation: true` / `Sunset: Sat, 01 Aug 2026 00:00:00 GMT` /
  `Link: </api/v1/files>; rel="successor-version"` HTTP header を付与。**v3.0
  で削除予定**。File API への移行を推奨
- **`pyflw-server --model-dir=PATH`** (= ADR-0041 §論点 3-A): CLI 引数単体使用
  時に `DeprecationWarning` 発火。**v3.0 で削除予定**、`--workspace=PATH` に
  移行
- **`POST /api/v1/simulations` body `model_id` field** (= ADR-0041 §論点 5-A):
  使用時に `DeprecationWarning`、**v3.0 で削除予定**。`model_path` (=
  workspace 相対) または `model` (= インライン dict) に移行

### Changed

- **`pyflw-server` 既定 workspace = CWD** (= 旧 `--model-dir=./models` 既定から
  変更、ADR-0041 §論点 3-A)。明示的な `--workspace=./models` または
  `--model-dir=./models` で旧挙動を維持可能 (legacy は deprecation warning
  発火)
- **`SimulationManager.start()`** signature: `model_path: Path` →
  `simulator: Simulator` (= ロード責務を route handler に移譲、ADR-0041 §5
  実装の副産物)。本変更は内部 API、外部 Public API には影響なし

### Internal / Tests

- **新規テスト 143 件** (= path traversal 68 + CLI 19 + File API 46 + 拡張
  simulations 17 + deprecation header 5)、合計 **pytest 1145 件 pass**
  + 2 skipped (= POSIX symlink テストが Windows で skip)
- **数値完全不変ガード**: `examples/spring_mass_damper.py` Final x=0.2505,
  x_dot=0.0031 (Phase 1 v0.1.0 baseline) を維持
- **mypy --strict / ruff lint clean**

### 移行ガイド (= v2.x → v3.0 で必要な変更の予告)

| 旧 (v2.x、warning 付きで動作) | 新 (v3.0 で必須) |
|---|---|
| `pyflw-server --model-dir=./models` | `pyflw-server --workspace=./project` |
| `POST /api/v1/simulations {model_id: "x"}` | `POST /api/v1/simulations {model_path: "x.flw.json"}` |
| `GET /api/v1/models/x` | `GET /api/v1/files/content?path=x.flw.json` |
| `PUT /api/v1/models/x` | `PUT /api/v1/files/content?path=x.flw.json` |
| `DELETE /api/v1/models/x` | `DELETE /api/v1/files?path=x.flw.json` |
| `GET /api/v1/models` (list) | `GET /api/v1/files/tree` |

frontend FileBrowser UI (= `selectedFilePath` state、左サイドバー tree、
context menu、dirty 確認モーダル、reload polling) は次の v2.x minor リリース
で実装予定 (ADR-0041 §論点 7〜11)。

## [0.15.0] - 2026-05-09 — GUI Simulink 化 (見た目 + 各ブロック表示 + enum select)

ユーザーフィードバック (= 「Simulink っぽくしてくれ」) を受けて、GUI の見た目と
各ブロックの表示を Simulink 互換に揃える minor リリース。Public API / JSON
schema / backend ロジックは無変更で v2.0.x からの後方互換あり。

### Visual changes (Simulink 互換)

- **連結線**: bezier (滑らかな曲線) → **`step` (90° 折れ)**、stroke を黒系細線
  (`#1e293b`、1.5px) に統一、終端に **矢印 head** (= `MarkerType.ArrowClosed`、
  8×8) を付加して「信号の流れ」を視覚化
- **ブロック輪郭**: 各 shape kind ごとの色 (青/紫/スレート) → **黒線統一**
  (`#1e293b`、1px、selected 時 1.5px 青)、`drop-shadow` 削除でフラット化、
  rect / bar の **角丸を全廃**
- **ブロック背景**: 白統一 (= Simulink 標準)
- **Subsystem / TriggeredSubsystem**: **二重枠** (= 内側 +3px に細線追加) で
  container と一目で分かる、base size 96×56
- **Mux / Demux**: width 18 → **6 px** の細い black bar (Simulink 互換)、
  chevron は黒バーに重ならないようバーの **外側に offset**
- **Port (handle)**: 円 → **線画 chevron `>`** (= 信号の流れ方向、未接続のみ
  表示、接続済は edge の矢印 head が代わりに方向を示す)

### Block-specific 表示

| Block | Before | After |
|---|---|---|
| Constant | `const` テキスト | **値そのもの** (`1.0`、`70` 等) |
| Inport / Outport | `in` / `out` | **ポート番号** (`port_idx + 1`) |
| Integrator | `∫` | **`1/s`** (分数表示) |
| UnitDelay | テキスト | **`1/z`** |
| DiscreteIntegrator | テキスト | **`Ts/(z-1)`** |
| Derivative | `du/dt` | **`s`** |
| TransferFunction | `num(s) / den(s)` static | **実際の多項式** (`2s+1` / `s^2+s+3`) |
| DiscreteTransferFunction | 同 | **z 多項式** |
| StateSpace 系 | `ẋ=Ax+Bu` | **行列サイズ** (`A: 2×2`) 付き |
| MimoTransferFunction | static | **代表多項式** + `[..., ...]` 略記 |
| Abs | V 字 icon | **`|u|`** テキスト |
| MinMax | 山形 icon | **`min`** / **`max`** テキスト (= `param.operator`) |
| Switch | スイッチ機構図 | **`u2 ≥ T`** 等 (= `param.criterion`) |
| Sign | 段差 icon | **`sign`** テキスト |
| Logical / Relational Operator | アイコン | **`AND`** / **`>=`** 等 (= `param.operator`) |
| Saturation / Step / Sine / Ramp / Pulse | 左 glyph 小 + 右 param 値 | **glyph 中央大配置** (= Simulink は icon only) |

### Added

- **`pyflw/web/frontend/src/lib/blockFormatting.ts`** (新規): 数値 / 多項式 /
  伝達関数 / 行列サイズの整形ユーティリティ。テスト容易な pure function 群
- **enum_values 機構** ([pyflw/server/registry.py:ParamSpec](pyflw/server/registry.py)
  + 各 block class の `_param_enums` class attribute):
  - `MinMax.operator` (= `min` / `max`)
  - `Switch.criterion` (= `>=` / `>` / `!=`)
  - `LogicalOperator.operator` (= `NOT` / `AND` / `OR` / `XOR` / `NAND` / `NOR`)
  - `RelationalOperator.operator` (= `<` / `<=` / `==` / `!=` / `>=` / `>`)
- **ParameterPanel が enum_values を `<select>`** で render
  ([components/ParameterPanel.tsx](pyflw/web/frontend/src/components/ParameterPanel.tsx)):
  許容値が限定された string param は自由入力でなくドロップダウンで選択 → UX
  改善 + 不正値混入防止

### Fixed (= GUI 改修中に発見した bug)

- **MinMax の表示が `paramsRaw.function` を読み違えていた** → 正しく `operator`
- **Switch の表示が `paramsRaw.criteria` を読み違えていた** → 正しく `criterion`
- **`edges.map` で `type: "smoothstep"` 強制上書き** していたため diagramConverter
  の `type: "step"` が無視されていた → 上書き撤廃、既存 edge も step 折れ線に
- **Mux / Demux の base 幅 (= 18px) > NodeResizer.minWidth (= 40px)** で resize
  ができない bug → shape kind ごとに minWidth を最適化 (bar=4、circle=28、
  triangle=32、trapezoid=36、rect-wide=56、rect=40)

### Tests / Compat

- pytest 1039 件 / vitest 208 件 all pass
- mypy --strict / ruff / sphinx -W すべて clean
- `examples/spring_mass_damper.py` 数値完全不変 (= Final x=0.2505)
- backend / Python API / JSON schema 0.8 / REST `/api/v1/*` は無変更
  (= v2.0 凍結維持、minor bump で互換性 OK)

### 後続予定

GUI 編集機能の Simulink 互換改善 (= 分岐点 waypoint 編集、edge 中点からの
右クリック分岐) は **ADR-0040 / v0.16.0** で別途設計。Public API レベルの
変更なし、純 frontend GUI の機能追加として進める。

## [0.14.2] - 2026-05-09 — portShapeValidate hotfix (Subsystem 派生)

### Fixed

- **Subsystem の入力ポートに connect しようとすると `n_inputs=0` で弾かれる
  バグ** ([pyflw/web/frontend/src/lib/portShapeValidate.ts](pyflw/web/frontend/src/lib/portShapeValidate.ts)):
  v2.0 で `dynamicPorts.resolvePortCounts` は派生計算に修正したが、connect
  検証側 (`getDefaultPortShapes`) は registry default を返したままで、Subsystem
  に内部 Inport を追加しても外側からの接続が `Subsystem_0.in[0] does not exist
  (n_inputs=0)` で拒否されていた。`getDefaultPortShapes` の Subsystem /
  TriggeredSubsystem branch を `params.blocks` 派生に切り替え、内部 Inport の
  ``port_shape`` (port_idx 順) を集めて返すよう修正。TriggeredSubsystem の
  trigger slot (= 末尾 scalar) も派生に含む。

### Tests

- ``tests/portShapeValidate.test.ts`` に 2 件追加 (= 計 15 件):
  - 内部 Inport 1 つ持つ Subsystem に connect が通ることを検証
  - TriggeredSubsystem の internal Inport / trigger slot / out-of-range の各
    ケース

### Compat / Risks

- pytest 1039 件 / vitest 208 件 (= +2) all pass、mypy / ruff / sphinx clean
- backend / Python API は無変更、frontend hotfix のみ

## [0.14.1] - 2026-05-09 — ADR-0039 follow-up + 再発防止

v0.14.0 の Subsystem 派生 property 化を完全に貫徹するための clean-up patch。
v1.0/v0.13.1/v2.0 の 3 連続 release で frontend bundle deploy をスキップし
続けた事故 (= ブラウザに ``pyflw v0.17.0`` が表示) の再発防止策も同梱。

### Fixed

- **GET ``/api/v1/models/{id}`` で migration が走らないバグ**
  ([pyflw/server/routes/models.py:46-65](pyflw/server/routes/models.py#L46))。schema
  0.6 / 0.7 形式のファイルがそのまま frontend に流れ、v2.0 派生 property 化と
  整合しないデータで描画されていた。``migrate_to_current`` を経由するように
  修正、test 1 件追加 (``TestGetModelMigration``)
- **MenuBar.tsx の hard-coded ``schema_version: "0.6"``**
  ([components/MenuBar.tsx](pyflw/web/frontend/src/components/MenuBar.tsx)) を
  最新 ``"0.8"`` (= ``CURRENT_SCHEMA_VERSION`` と整合) に更新。新規モデル作成
  時の無駄な migration を回避
- **``_BUILTIN_DEFAULT_ARGS`` の Subsystem / TriggeredSubsystem ゴミエントリ
  削除** ([pyflw/server/registry.py:281-286](pyflw/server/registry.py#L281))。
  v2.0 で廃止された ``n_inputs=1, n_outputs=1`` を default 引数として登録
  していたため ``_instantiate_for_introspection`` で TypeError → 第 2 試行
  という無駄な経路を経由していた。エントリ自体を削除して直接 ``cls()`` で
  空 Subsystem 生成

### Added (再発防止)

- **postbuild deploy script** (``pyflw/web/frontend/scripts/deploy-to-server-static.mjs``):
  ``npm run build`` 一発で ``dist/`` から ``pyflw/server/static/`` へ自動 copy
  + 古いハッシュ bundle 一掃 + ``.app-version`` マーカー書き出し。``npm run
  build:no-deploy`` で従来挙動 (deploy なし) も保持。
- **起動時 frontend bundle version mismatch warning**
  ([pyflw/server/app.py:_check_frontend_bundle_version](pyflw/server/app.py)):
  ``pyflw-server`` 起動時に ``pyflw/server/static/.app-version`` を読んで
  backend ``pyflw.__version__`` と比較、ズレていれば WARNING ログ。bundle が
  古いまま release した事故を早期検知。

### Changed

- backend / frontend version bump 2.0.0 → 2.0.1
- ``.claude/pending_updates.md`` に「frontend を含む release では bundle
  deploy を verify chain に必須化」エントリ追加 (``/reflect`` で正式採否判定)

### Tests

- ``tests/server/test_models_api.py::TestGetModelMigration`` 1 件 — schema
  0.7 形式ファイルを直置きして GET → 最新 schema (= 0.8) で migration 結果が
  返ることを検証

### Compat / Risks

- pytest **1037** all pass (= v0.14.0 の 1036 + 新規 1 件)
- vitest 206 件 / typecheck / mypy --strict / ruff / ruff format / sphinx -W
  すべて clean
- ``examples/spring_mass_damper.py`` 数値完全不変 (Final x=0.2505)
- 旧 schema ファイル (= 0.5 / 0.6 / 0.7) を持つ既存ユーザーは GET 経由で
  自動 migration、修正前の対症療法 (= ブラウザリロード等) は不要
- **既知の drift リスク**: ``MenuBar.tsx`` の ``CURRENT_SCHEMA_VERSION`` は
  hard-coded のため、次回 schema 0.9 を bump する時に backend と同時に
  frontend も更新する必要がある。中期的には ``GET /api/v1/info`` 等で
  backend から取得する設計を検討 (= ADR-0040 候補)

## [0.14.0] - 2026-05-09 — BREAKING

ADR-0039 で **Subsystem の port semantics を SSOT 是正**。``n_inputs`` /
``n_outputs`` / ``port_shapes_in`` / ``port_shapes_out`` を **派生 property**
に格上げし、Python API と JSON schema から廃止する。利用者ゼロ + PyPI 未公開
のうちに「内部 Inport / Outport の集合 = 真実」「外側 port count = 派生計算」
という Simulink semantics 整合の正しい設計に戻す。ADR-0038 で凍結した
v1.0 Public API は本リリースで部分 supersede (= ADR-0038 §Amendments §(1))。

### Rationale

v0.13.1 patch の "frontend で auto-sync" は対症療法だった。本来は
``Subsystem.n_inputs`` を property で ``len(self._inports)`` から派生させる
形が SSOT 原則と一致する。利用者がいない開発段階の今が直すコスト最小。
詳細は [ADR-0039](.claude/docs/adr/0039-subsystem-port-derived-property-v2.md)。

### Removed (BREAKING)

- ``Subsystem(n_inputs=N, n_outputs=M, port_shapes_in=..., port_shapes_out=...)``
  コンストラクタ引数が完全廃止。**渡すと `TypeError`**。
- ``TriggeredSubsystem(n_inputs=N, n_outputs=M, ...)`` も同様。
- JSON schema 0.7 の ``params.n_inputs`` / ``params.n_outputs`` /
  ``params.port_shapes_in`` / ``params.port_shapes_out`` フィールドを削除。
- `libraries.v1` schema は **`libraries.v2` に bump**、subsystem body 内の
  上記フィールドが削除される。

### Migration guide

```python
# Before (v1.x)
sub = Subsystem(n_inputs=2, n_outputs=1, blocks=[
    Inport(port_idx=0, port_shape=(3,)),
    Inport(port_idx=1),
    Outport(port_idx=0),
])

# After (v2.0)
sub = Subsystem(blocks=[
    Inport(port_idx=0, port_shape=(3,)),
    Inport(port_idx=1),
    Outport(port_idx=0),
])
# n_inputs / n_outputs / port_shapes_in / port_shapes_out は内部 Inport /
# Outport から自動派生される
assert sub.n_inputs == 2
assert sub.n_outputs == 1
assert sub.port_shapes_in == ((3,), ())
```

JSON モデルファイル (``.flw.json``) は **schema 0.7 → 0.8 自動 migration**
で読み捨てられる。利用者の手作業は不要 (= load 時に
``_builtin_migrate_0_7_to_0_8`` が走る)。

### Changed

- ``CURRENT_SCHEMA_VERSION = "0.8"`` ([pyflw/core/persistence.py:30](pyflw/core/persistence.py#L30))
- ``CURRENT_LIBRARY_SCHEMA_VERSION = "libraries.v2"`` ([pyflw/libraries/_loader.py:34](pyflw/libraries/_loader.py#L34))
- ``Subsystem.n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
  ``port_shapes_out`` を **property override** (= 内部 Inport / Outport から
  毎回算出、cache なし)。setter は silent no-op で ``Block.__init__`` の代入
  を吸収。
- ``Subsystem.add(Inport)`` で外側 ``self.input_sources`` を 1 個拡張 (=
  Block 契約「input_sources の長さ == n_inputs」を維持)。
- ``TriggeredSubsystem.add(Inport)`` で末尾 trigger slot を保持しつつ
  内部 Inport slot を 1 つ前に挿入。
- ``Subsystem._build`` の「内部 Inport 数 == n_inputs」count assert を削除
  (= 派生で自動成立)。port_idx 連番検証は維持。
- ``Subsystem.to_dict()`` から ``n_inputs`` / ``n_outputs`` /
  ``port_shapes_in`` / ``port_shapes_out`` キー削除。
- ``Subsystem._from_dict`` / ``TriggeredSubsystem._from_dict`` で legacy
  フィールドを ``**legacy_kwargs`` で受け取って警告 + 読み捨て (= migration
  経由で来ない直接 load 時の defensive)。

### Added

- ``_builtin_migrate_0_7_to_0_8`` ([pyflw/core/persistence.py:323](pyflw/core/persistence.py#L323))
  schema 0.7 → 0.8 migration。再帰的に Subsystem entry を走査、派生 4
  フィールドを除去、内部 Inport / Outport 数との不一致は warning。
- ``_migrate_libraries_v1_to_v2`` ([pyflw/libraries/_loader.py:42](pyflw/libraries/_loader.py#L42))
  libraries.v1 → v2 migration。subsystem body に対して 0.7 → 0.8 ヘルパを
  そのまま流用。
- ``scripts/regenerate_std_library.py`` 一度きりの再生成スクリプト。
- ``pyflw/libraries/std.flwlib.json`` を `libraries.v2` 形式で再生成 (= 派生
  フィールド除去、entry id `pid_controller` / `first_order_plant` /
  `second_order_plant` は不変)。
- 新規テスト:
  - ``tests/subsystems/test_port_derived_property.py`` (17 件) — 派生 property
    + port_idx 連番強制 + TriggeredSubsystem trigger slot
  - ``tests/test_persistence_migration_0_7_to_0_8.py`` (6 件) — schema
    migration + nested Subsystem 再帰 + 不一致 warning + TriggeredSubsystem
    内部 +1 trigger
  - ``pyflw/web/frontend/tests/dynamicPortsSubsystem.test.ts`` (5 件) —
    ``resolvePortCounts`` の派生計算
  - ``pyflw/web/frontend/tests/subsystemPortAutoResize.test.ts`` (8 件、書き
    換え) — port_idx 自動採番 + 連番再割り当て + 親 connections シフト +
    TriggeredSubsystem trigger shift

### Frontend

- ``dynamicPorts.resolvePortCounts`` の Subsystem branch を派生計算に変更
  (= ``params.blocks.filter(b => b.type === INPORT_TYPE).length``)。
  TriggeredSubsystem は ``+1`` (trigger 分)。
- ``appStore.ts`` の v0.13.1 で追加した ``params.n_inputs`` / ``n_outputs``
  同期ロジックを削除 (= 派生計算で自動成立、約 80 行削減)。port_idx 自動
  採番 / 連番再割り当て / 親 connections シフト / TriggeredSubsystem
  trigger shift は維持 (= ADR-0039 §Decision §(7))。

### Compat / Risks

- pytest 1036+ 件 all pass (= v0.13.1 baseline 1015 + 新規 23 + 削除分の
  差し引き)
- vitest 全件 all pass、bundle gzip サイズ減 (= auto-resize 削減)
- mypy --strict / ruff / sphinx -W すべて clean
- ``examples/spring_mass_damper.py`` 数値完全不変 (= Subsystem を含まない
  ので影響ゼロ、v0.1.0 baseline 維持)
- ADR-0038 の v1.0 凍結は本リリースで部分 supersede (= ADR-0038 §Amendments)
- Phase 6 親 ADR の番号は ADR-0040 に繰り下げ (= ADR-0038 §Amendments §(2))

### References

- [ADR-0039: Subsystem port 派生 property + v2.0](.claude/docs/adr/0039-subsystem-port-derived-property-v2.md)
  (Accepted、2026-05-09)
- [ADR-0038 §Amendments §(1)(2)](.claude/docs/adr/0038-phase5-closure-and-v1-judgment.md)
  — v1.0 凍結部分 supersede + 番号繰り下げ
- ADR-0009 (Subsystem 階層、Inport/Outport の原典)、ADR-0036
  (TriggeredSubsystem trigger slot)、ADR-0029 (libraries.v1 → v2 予告回収)

## [0.13.1] - 2026-05-09

GUI bug fix patch。Public API / JSON schema / REST / extras 名は v0.13.0
から無変更で **凍結維持**。

### Fixed

- **Subsystem ドリルダウン中の Inport / Outport 追加・削除で親ノードの
  ポート数が同期しないバグ** (`pyflw/web/frontend/src/store/appStore.ts`)。
  Simulink semantics に合わせて以下を実装:
  - Inport / Outport drop 時、親 Subsystem の ``n_inputs`` / ``n_outputs``
    を +1、新ブロックの ``port_idx`` を内部既存同種 count に自動採番
  - Inport / Outport 削除時、親 ``n_inputs`` / ``n_outputs`` を -1、残った
    同種 ports の ``port_idx`` を連番再割り当て、親階層 connections の
    ``dst_idx`` (Inport) / ``src_idx`` (Outport) を追従シフト
  - **TriggeredSubsystem** の trigger 接続 (= 末尾 ``dst_idx = n_inputs - 1``
    固定 slot、ADR-0036 §(2)) も Inport 追加・削除に応じて自動シフト
  - 修正前は内部 Inport 数 != ``n_inputs`` の不整合状態で save され、
    backend ``Subsystem._build`` が ``BlockSpecError`` を投げる構造だった
  - 詳細: ``.claude/docs/bug-reports/2026-05-09-subsystem-port-auto-resize.md``

### Added

- ``pyflw/web/frontend/src/lib/blockTypes.ts`` (新規): Subsystem / Inport /
  Outport / TriggeredSubsystem の ``type_path`` 定数を集約、``getNumberParam``
  型ガード関数で ``params`` を number として安全に取り出す (= NaN 混入回避)。
  ``appStore.ts`` と新規テストの両方から import

### Tests

- ``tests/subsystemPortAutoResize.test.ts`` (新規): 9 ケース
  (Inport/Outport 追加 + 削除 + 中間連番再割り当て + TriggeredSubsystem
  trigger shift + port_idx 欠落防御 + top-level no-op)

### Compat / Risks

- vitest 202 件 all pass (= v0.13.0 の 193 件 + 新規 9 件)、frontend
  typecheck clean
- pytest 1015 件 all pass (= backend 影響ゼロを確認)
- Backend / REST / JSON schema 0.7 / Python API は無変更で v1.0 凍結維持
- bundle 増分 ~0.5 KB gzip 程度 (= 新規 ``blockTypes.ts`` 微小)

## [0.13.0] - 2026-05-09

**Phase 5 complete — pyflw stable**。ADR-0038 (Phase 5 closure + v0.13.0 判定)
を Accepted とし、v0.17.0 → v0.13.0 へ major bump。Public API + JSON schema 0.7 +
REST `/api/v1/*` + extras 名 (`pyflw[gui/control/codegen/gpu]`) を v1.0 として
fix、以降 breaking change は v2.0 を要する SemVer 厳守体制に移行する。

### Added

- ``pyflw[gpu]`` extras (= ``jax[cuda12]>=0.4,<0.5``、NVIDIA CUDA 12 / Linux
  x86_64 wheel only)。実機ベンチマークと CI 整備は Phase 6+ ADR-0039 で着手、
  v1.0 では best-effort 扱い (= SPEC §非機能要件「state size >= 10^5 で CPU
  比 5x 以上を **目標**」と整合)
- ``README.md`` Codegen / Autodiff セクション (= ``Simulator.compile()`` +
  ``linearize(method="jax")`` の最小例)、Stable as of v1.0 注記
- ``docs/index.rst`` に Stable as of v1.0 注記、凍結範囲を明示

### Changed

- ``README.md`` Requirements: ``Python 3.10+`` → ``Python 3.11+`` 修正
  (= ADR-0035 / v0.15.0 で ``requires-python = ">=3.11"`` に bump 済の
  反映漏れ修正)、Block Library 表に RateTransition / TriggeredSubsystem /
  Display / XYGraph / Mux / Demux / MimoTransferFunction を反映
- ADR-0031 / ADR-0036 / ADR-0037 のヘッダに
  ``Phase 5 closed by ADR-0038 (v0.13.0, 2026-05-09)`` を追記
- SPEC-0001 §機能要件 Phase 5 の項目 #31〜#36 を ``[x]`` 完了状態に更新、
  §Phase 6+ を ADR-0038 §論点 5 表で再整理 (= jax 拡張 / Diffrax / GPU 実機 /
  array_backend / 追加言語 / E4 Settings panel / 3D ビュー / 最適化ソルバー /
  Monte Carlo / C コード生成 / HIL / ダークモード永続)

### Phase 5 全体総括

- **Phase 5a (配布基盤 + 借入金返済)**:
  - ADR-0032 (PyPI 自動化、v0.13.0): Trusted Publishers + GitHub Actions
    release workflow 整備済 (実 publish はユーザー任意)
  - ADR-0033 (ZeroOrderHold legacy 削除、v0.13.0): ADR-0014 §(4) で
    v0.5.0 から発行してきた deprecation 完済
  - ADR-0035 (Python 3.11+ + strict typing 復元、v0.15.0): Python 3.10 EOL
    5 ヶ月前倒し、``disallow_any_generics = true`` 復元、numpy 2.3+ TypeVar
    default 採用、bare ``np.ndarray`` を ``npt.NDArray[Any]`` に全置換、
    ``tomli`` 条件付き dep 削除
  - ADR-0034 (ダークモード) は永続的 out-of-scope (ADR-0031 §Amendments、
    user memory ``feedback_no_dark_mode``)、v0.14.0 タグは欠番
- **Phase 5b (コア大改修)**:
  - ADR-0036 (RateTransition + TriggeredSubsystem、v0.16.0 / v0.16.1):
    Option B priority queue ベースのスケジューラ拡張、構造的不変性ガード
    (= 該当ブロック未使用なら数値挙動不変) 達成
  - ADR-0037 (jax-first Codegen + Autodiff、v0.17.0): ``Simulator.compile()``
    + ``linearize(method="jax")`` で機械精度 (``atol=1e-12``) 自動微分。
    numba / cupy / numba.cuda は棄却、jax 1 本で GPU + Codegen + Autodiff を
    統合
  - ADR-0038 (Phase 5 closure + v0.13.0 判定、v0.13.0): SPEC §スコープ
    14 項目を表で全評価 (14/14 達成または extras 経路で達成)、Plan B 採用
    (= 元 v0.17.1 GPU benchmark / v0.17.2 array_backend を Phase 6+ 送り)、
    Public API 凍結範囲を 9 項目で確定

### Public API 凍結範囲 (= ADR-0038 §論点 2)

以降 breaking change は v2.0 を要する。凍結対象:

- **Block 基底契約**: ``Block.output(t, x, u)`` / ``derivative(t, x, u)`` /
  ``update(t, x, u)`` シグネチャ、``direct_feedthrough`` / ``n_states`` /
  ``port_shapes`` 宣言
- **Simulator 公開 API**: ``add`` / ``connect`` / ``run`` / ``compile`` /
  ``save`` / ``load``、``Simulator(t_end, dt, solver=...)`` コンストラクタ
- **38 ブロック** (v0.17.0 時点、RateTransition / TriggeredSubsystem 含む) の
  クラス + コンストラクタ引数
- **解析 API**: ``linearize`` (``method="central" / "forward" / "jax"``)、
  ``bode`` / ``nyquist`` / ``eigenvalues`` / ``is_stable`` / ``root_locus``
- **Codegen API**: ``Simulator.compile(backend="jax" | "numpy")``、
  ``CompiledSimulator`` frozen dataclass の公開フィールド
- **JSON schema 0.7** (= ADR-0036 で bump)、以降の minor bump は migration
  関数を必須提供
- **REST API**: ``/api/v1/blocks`` (``blocks.v2``) / ``/api/v1/libraries``
  (``libraries.v1``) / ``/api/v1/models`` / ``/api/v1/simulate/*`` /
  WebSocket ``/ws/*``。breaking 変更は ``/api/v2/`` 別系統で許容
- **Library file schema**: ``LibraryFile`` (``libraries.v1``)、組み込み
  ``std.flwlib.json`` の 3 entry ID
- **extras 名**: ``pyflw[gui]`` / ``pyflw[control]`` / ``pyflw[codegen]`` /
  ``pyflw[gpu]``。依存パッケージのバージョン pin は v1.x で更新可

凍結しない (= v1.x で改修可): 内部実装 (``_`` prefix)、frontend 内部
component 構造、``CompiledSimulator.step`` / ``run`` の本格実装、エラー
メッセージ文言。

### Phase 6+ 引き渡し (= ADR-0038 §論点 5)

ADR-0039 (Phase 6 親 ADR) で別途整理:

- GPU 実機 benchmark + ``pyflw[gpu]`` CI 整備 (元 v0.17.1)
- ``pyflw.array_backend`` 抽象化 (元 v0.17.2、実需が立った時点で起動)
- ``StateSpace`` / ``TransferFunction`` / ``MimoTransferFunction`` /
  ``DiscreteIntegrator`` / ``UnitDelay`` / ``ZeroOrderHoldDirect`` /
  ``Subsystem`` / ``TriggeredSubsystem`` の jax tracing
- 連続 ODE の Diffrax 連携 (= ``CompiledSimulator.run()`` の本格実装)
- 追加言語 (zh / ko / ar) + RTL (ADR-0024 §Phase 4 送り → Phase 6+)
- 連続 trigger / 可変ステップ離散の一般 API (ADR-0036 §(11))
- E4 Settings panel (editor preferences、ADR-0031 §Amendments)
- アニメーション 3D ビュー / 最適化ソルバー連携 / Monte Carlo (SPEC §未達)
- C コード生成 / HIL は本プロジェクトでは現状やらない
- ダークモードは永続的 out-of-scope (memory ``feedback_no_dark_mode``)、
  提案禁止

### Compat / Risks

- pytest 1015 件 / vitest 193 件 all pass (= v0.17.0 baseline 維持)
- mypy --strict / ruff / sphinx -W すべて clean
- bundle gzip 185.78 KB (= ADR-0023 予算 1 MB の 18.6%、Phase 4 完了時
  から不変)
- ``examples/spring_mass_damper.py`` 数値完全不変 (= Final x=0.2505,
  x_dot=0.0031、Phase 1 v0.1.0 baseline 維持)
- ``Simulator.compile()`` で未対応ブロックを含むモデルは ``BlockSpecError``
  で拒否、利用者からの「v1.0 なのに compile できない」指摘は Phase 6+ で
  段階対応 (= Public API 不変なので v1.x の minor リリースで吸収可)
- ``CompiledSimulator.step`` / ``run`` は ``NotImplementedError`` stub のまま
  v1.0、API shape は凍結済、本格実装は v1.x で追加可
- PyPI 初版 publish はユーザー任意のタイミング (memory
  ``feedback_pypi_user_responsibility``)。git tag ``v0.13.0`` push 時点で
  workflow が走るが、発火タイミングはユーザー判断

## [0.17.0] - 2026-05-09

**Phase 5b コア改修 — jax-first Codegen + Autodiff**。ADR-0037 採択 (jax-first
統合戦略) を実装。``Simulator.compile()`` API を opt-in で導入し、ADR-0026 の
線形化に **機械精度自動微分 (`method="jax"`)** を追加する。numba / cupy /
numba.cuda は棄却、jax 1 本で GPU + Codegen + Autodiff を統合。

### Added

- ``pyflw.compile`` モジュール (ADR-0037 §(2)):
  - ``CompiledSimulator`` frozen dataclass (= ``Simulator.compile()`` の戻り値)
  - ``Simulator.compile(backend="jax" | "numpy")`` メソッド
  - ``CompiledSimulator.linearize()`` (= ``method`` を backend に応じて自動選択)
  - ``step()`` / ``run()`` は v0.17.1+ で本格実装の予定 (現状 NotImplementedError)
- ``pyflw.compile.jax_backend`` (ADR-0037 §(3)):
  - jax-native 評価器 ``_evaluate_jax``、ADR-0014/0015 と同じ 2-pass topo 順 +
    direct-feedthrough/non-df 区別
  - ``linearize_via_jacfwd`` (= ``jax.jacfwd`` で (A,B,C,D) 計算)
  - サポート block: Constant / Step / Sine / Ramp / Clock / Gain / Sum /
    Integrator (= 線形 LTI MVP)、未サポートは ``BlockSpecError`` で
    ``method="central"`` への切替を案内
- ``pyflw.linearize(method="jax")`` (ADR-0026 §「Phase 5+ で再評価」回収):
  - ADR-0026 の NotImplementedError stub を ``jax.jacfwd`` 経由実装に置換
  - ``central`` / ``forward`` semantics は完全維持
  - spring_mass_damper モデルで解析解と機械精度 (atol=1e-12) 一致を CI で pin

### Changed

- ``[project.optional-dependencies] codegen = ["jax[cpu]>=0.4,<0.5"]`` extras 追加
- ``[project.optional-dependencies] dev`` に ``jax[cpu]`` を追加 (= CI で
  ``method="jax"`` テストを必須走らせる)
- ``[tool.mypy] strict = true`` 維持、jax コードも厳格 typing 準拠

### Behavior

- **opt-in 設計** (ADR-0036 §(8) / ADR-0037 §(8) 数値完全不変ガード継承):
  ``Simulator.compile()`` を呼び出さない限り numpy ホットパスがそのまま動く。
  ``examples/spring_mass_damper.py`` の出力数値は v0.16.1 から不変
  (Final x=0.2505, x_dot=0.0031)
- ``pyflw[codegen]`` 未インストール環境では ``Simulator.compile(backend="jax")``
  / ``linearize(method="jax")`` が ``ImportError`` で明示失敗 (= silent fallback
  しない)
- ``TriggeredSubsystem`` を含むモデルでは ``Simulator.compile()`` が
  ``BlockSpecError`` で拒否 (= ADR-0036 §(9) MVP scope、Phase 6+ で別 ADR)

### Tests / Examples

- ``tests/test_linearize_jax_consistency.py`` (10 件): central と jax の機械
  精度一致、解析解との一致、未サポートブロックエラー、``CompiledSimulator``
  経路の動作確認
- ``examples/jax_jacfwd_pid.py``: PID + 1 次プラントの閉ループを ``method="jax"``
  で線形化、固有値計算による安定性判定 demo

### Compat / Risks

- pytest 1015 件 (= v0.16.1 の 1005 件 + 10 件 jax consistency) 全 pass
- vitest 193 件 / mypy --strict / ruff / sphinx -W すべて clean
- bundle gzip 不変 (= 純 Python 実装、frontend 影響なし)
- jax 0.4.x dtype = float64 強制 (`jax_enable_x64=True`)、numpy default と整合

### Phase 6+ への引き渡し (ADR-0037 §Decision §(11))

- ``StateSpace`` / ``TransferFunction`` / ``MimoTransferFunction`` の jax 対応
- ``DiscreteIntegrator`` / ``UnitDelay`` / ``ZeroOrderHoldDirect`` の jax 対応
- ``Subsystem`` 内部ブロックの jax tracing
- ``TriggeredSubsystem`` の jit 化
- ``cupy`` / ``array-api-strict`` の代替バックエンド
- 連続 ODE の Diffrax 連携 (= ``CompiledSimulator.run()`` の本格実装)
- Apple Silicon / ROCm / TPU バックエンド

### Phase 5b の次

ADR-0037 §(8) commit 計画に従い v0.17.1 で:
- ``pyflw[gpu]`` extras (= ``jax[cuda12]``)
- GPU benchmark (= ユーザー実機検証)
- CI Windows skip ロジック整理

その後 v0.17.2 で ``pyflw.array_backend`` 抽象化、最終的に Phase 5 完了
(ADR-0038 / v0.13.0 判定) へ。

## [0.16.1] - 2026-05-09

**Phase 5b 中間 — TriggeredSubsystem (edge-driven fire)**。ADR-0036 後半の
リリース。トリガー信号の rising/falling/either edge でのみ内部ブロックを
発火するサブシステムを追加 (Simulink Triggered Subsystem 互換)。

### Added

- ``pyflw.TriggeredSubsystem`` (ADR-0036 §(2)): :class:`pyflw.Subsystem` を継承、
  trigger 入力は **入力末尾** (``input_sources[-1]``) 固定で内部に流さない。
  - ``trigger_mode``: ``"rising"`` / ``"falling"`` / ``"either"`` (default ``"rising"``)
  - 内部ブロックは **edge 検出時のみ** ``output`` / ``update`` が呼ばれる。
    fire しないステップでは内部状態凍結 + 前回出力 (``_last_y``) をキャッシュ
  - NaN sentinel で起動時の偽 edge を防止 (= ``_prev_trigger_value`` 初期値 NaN)
  - ``_build`` override で内部 Inport 数 ``n_inputs - 1`` を許容
  - ``to_dict`` / ``_from_dict`` override で ``trigger_mode`` を JSON round-trip
- ``pyflw.subsystems.triggered._is_trigger_edge``: rising/falling/either 共通
  edge 判定 helper
- Block class registry (ADR-0019 §(1)) に TriggeredSubsystem 登録 (= category
  ``subsystems``、``is_container=True``、ja/en 翻訳付き)
- frontend block palette に Subsystems カテゴリで TriggeredSubsystem 表示、
  専用 SVG glyph (= Subsystem rect + 雷マーク)

### Phase 5b MVP 制約 (ADR-0036 §(4-C))

- **離散信号 trigger のみ**対応。連続信号からの zero-crossing 検出は将来 Phase
  で別 ADR 化 (= ``solve_ivp(events=...)`` 統合の検討)
- TriggeredSubsystem 内部の連続状態は fire 中のみ進む (= fire していないステップでは
  ``derivative=0`` で凍結)、warning ログを 1 度発出

### Compat / Risks

- pytest 1005 件 (= v0.16.0 の 974 件 + 31 件 TriggeredSubsystem) 全 pass
- vitest 193 件 / mypy --strict / ruff / sphinx -W clean
- ``examples/spring_mass_damper.py`` 出力数値完全不変 (= ADR-0036 §(8) 構造的
  不変性ガード達成: TriggeredSubsystem を含まないモデルでは ``Simulator`` の
  実行経路は本 ADR 前と完全一致)
- bundle gzip 増分 ≤ +2 KB (= ADR-0023 予算 1 MB の 18.7 → 18.7%)
- JSON schema は 0.7 のまま (= v0.16.0 で bump 済、TriggeredSubsystem も 0.7
  schema で永続化される)

### Phase 5b の次

ADR-0037 (Codegen + GPU + ``pyflw.array_backend``) に進む (v0.17.0)。
TriggeredSubsystem は ADR-0037 MVP では Codegen out-of-scope (= Python
fallback)、JIT 化は Phase 6+ 検討。

## [0.16.0] - 2026-05-09

**Phase 5b ローンチ — RateTransition Block + JSON schema 0.7**。Phase 5b
最初の sub-ADR (ADR-0036) の前半リリース。マルチレートモデルで異なるサンプル
時間を持つブロック間のレート変換を明示的に行う ``RateTransition`` を追加。

### Added

- ``pyflw.blocks.RateTransition`` (ADR-0036 §(1)): Simulink RateTransition 互換。
  - ``mode="zoh"`` (fast-to-slow ラッチ) / ``"delay"`` (slow-to-fast 1-step 遅延)
    / ``"auto"`` (input/output 周期から自動決定、default)
  - n_states=2、ADR-0015 §(2) の 2-state ローテーション流用
  - ``_resolved_sample_time = output_sample_time`` (= 下流レートで fire)、
    既存 ``_run_sm_a_loop`` の発火経路で動作 (= 新スケジューラ不要)
  - 引数バリデーション: 同一レート / 0 以下 / mode 不正で ``BlockSpecError``
- Block class registry (ADR-0019 §(1)) に RateTransition 登録、ja/en 翻訳追加
- frontend block palette に Discrete カテゴリで表示、専用 SVG glyph と
  ``input → output`` 周期表示の node label

### Changed (BREAKING — schema)

- ``CURRENT_SCHEMA_VERSION = "0.6"`` → ``"0.7"`` (ADR-0036 §(4))。
  ``_builtin_migrate_0_6_to_0_7`` は schema_version 文字列のみ更新する no-op
  (= 既存 0.6 ファイルに新 type_path は出現しないため、意味論変化なしで 100%
  互換)。0.6 ファイルは load 時に自動 migrate、save は 0.7 で行う

### Compat / Risks

- pytest 974 件 (= v0.15.0 から +25、RateTransition 21 + registry 2 + migration 2)
  / vitest 193 件 全 pass
- mypy --strict / ruff / sphinx -W clean
- ``examples/spring_mass_damper.py`` 出力数値完全不変 (= ADR-0036 §(8) 数値
  完全不変ガード)
- frontend bundle 増分 ≤ +2 KB gzip (= ADR-0023 予算 1 MB の 18.6 → 18.7%)

### Phase 5b の次

ADR-0036 §(8) commit 計画に従い、v0.16.1 で:
- TriggeredSubsystem (= rising/falling/either edge トリガーで内部発火)
- Priority queue layer (= 既存モデルで 1 行も変えない構造的不変性)

その後 v0.17.0 (ADR-0037 Codegen + GPU + array_backend) → v0.13.0 判定
(ADR-0038)。

## [0.15.0] - 2026-05-09

**Phase 5a 完了 — Python 3.11+ + strict typing 完全復元 (BREAKING)**。
Phase 5a 最後の sub-ADR (ADR-0035)。Phase 4 v0.12.0 hotfix で導入していた
``disallow_any_generics = false`` 借入金を Python 3.10 EOL (2026-10) より
5 ヶ月前倒しで完済し、mypy ``--strict`` を完全復元する。

**v0.14.0 は欠番** (= ADR-0034 ダークモード + Settings panel が 2026-05-08
ユーザー判断で永続的に out-of-scope となったため、ADR-0031 §Amendments)。

### Changed (BREAKING)

- ``requires-python``: ``>=3.10`` → ``>=3.11``。**Python 3.10 サポート終了**
  (= EOL 2026-10、numpy 2.3+ が Python 3.11+ 要求)。Python 3.10 利用者は
  ``v0.13.0`` で停止、``v0.15.0`` 以降は 3.11+ 必須
- ``numpy>=1.24`` → ``numpy>=2.3`` (= ``ndarray`` の PEP 696 TypeVar default
  を活用、bare ``np.ndarray`` も 3.11+ なら strict mypy を通る)

### Changed (typing)

- pyflw コア API シグネチャの bare ``np.ndarray`` を ``npt.NDArray[Any]`` に
  全面置換 (17 ファイル、約 330 箇所)。**runtime 動作は完全不変** (=
  ``npt.NDArray[T]`` は ``np.ndarray[Any, np.dtype[T]]`` の typing alias)。
  下流コードで ``mypy --strict`` を使う利用者は、自身の ``np.ndarray``
  annotation も ``npt.NDArray[Any]`` (= 推奨) または同等の parametrized 形に
  更新を検討
- ``[tool.mypy] disallow_any_generics`` を ``false`` (Phase 4 hotfix で緩めて
  いた値) から ``--strict`` default の ``true`` に復元。bare ``np.ndarray`` 等の
  型パラメータ無し generic を CI で検出
- ``[tool.mypy] python_version = "3.11"``、``[tool.ruff] target-version =
  "py311"`` (= 3.11 specific pyupgrade rules を有効化)
- ``pyflw/core/simulator.py``: ``datetime.timezone.utc`` → ``datetime.UTC``
  (= 3.11 alias、ruff UP 検出)

### Removed

- ``[project.optional-dependencies] dev`` から ``tomli>=2.0; python_version <
  '3.11'`` を削除 (= ``tomllib`` stdlib 利用)
- ``tests/test_version_consistency.py`` / ``tools/check_version_sync.py`` の
  ``sys.version_info >= (3, 11)`` 分岐を削除し ``import tomllib`` 一発に統一

### CI

- ``.github/workflows/ci.yml`` matrix を 3.10 抜きに更新:
  - ``lint-and-type``: ``["3.10", "3.13"]`` → ``["3.11", "3.13"]``
  - ``test``: ``["3.10", "3.11", "3.12", "3.13"]`` →
    ``["3.11", "3.12", "3.13"]``

### Compat / Risks

- pytest 949 件 / vitest 193 件 全 pass
- mypy --strict (= ``disallow_any_generics = true`` 復元) clean
- ruff / sphinx -W clean
- ``examples/spring_mass_damper.py`` 出力数値完全不変
- bundle gzip 不変 (frontend 影響無し)

### Phase 5a 完了

ADR-0031 §Phase 5a / 5b 境界 (= Python 3.11+ 移行完了) を満たし、Phase 5a
完了。次は Phase 5b コア大改修 (ADR-0036 マルチレート → ADR-0037 Codegen + GPU
+ array_backend → ADR-0038 v0.13.0 判定)。

## [0.13.0] - 2026-05-09

**Phase 5a ローンチ — 配布基盤 + 借入金返済**。ADR-0031 (Phase 5 全体方針) で
確定した Phase 5 を 2 段階構成 (5a 軽量 → 5b コア大改修) で進める前半の
最初のリリース。

ADR-0034 (ダークモード + Settings panel 統合、当初 v0.14.0 予定) は
**2026-05-08 ユーザー判断で永続的に out-of-scope** に変更 (ADR-0031
§Amendments)。Phase 5a の sub-ADR は ADR-0032 / ADR-0033 / ADR-0035 の 3 本
に縮小、`v0.14.0` タグは欠番。

### Added — PyPI publishing automation (ADR-0032)

- `.github/workflows/pypi-publish.yml`: Trusted Publishers (OIDC) ベースの
  TestPyPI → PyPI 2 段階 publish workflow。tag push (`v*`) で起動、
  PEP 440 準拠の final/pre-release 判定 (final tag のみ本 PyPI)。
- `tools/check_version_sync.py`: 3 ファイル version 同期検証
  (`pyflw/__init__.py` + `pyproject.toml` + `pyflw/web/frontend/package.json`)。
  CI / release.yml / pypi-publish.yml の 3 箇所で fail-fast。
- `docs/release_runbook.md`: 事前準備 (Trusted Publisher 登録 + GitHub
  environments 作成) と通常 release 手順、失敗時 rollback (yank → patch
  bump) を集約。
- `tests/test_version_consistency.py`: `package.json` version check 追加
  (= 既存 pyproject 整合 test を 3 ファイル化)。

### Changed — Release workflow

- `.github/workflows/release.yml`: 既存の version sync step を 3 ファイル
  整合に拡張 (`tools/check_version_sync.py` 呼び出しに置換)。GitHub
  Releases upload は維持。
- `.github/workflows/ci.yml`: lint-and-type job に version sync 検証 step
  を追加 (= push 時の事故予防)。

### Removed — ZeroOrderHold (legacy) (ADR-0033, **BREAKING**)

`ZeroOrderHold` (legacy 2-state state-based ホールド) を完全削除。ADR-0014
(v0.3.0) で `Simulator.run()` が修正されて以降、`UnitDelay` と完全同一の
semantics になっており、v0.5.0 から `DeprecationWarning` を発出してきた。
8 minor versions の deprecation cycle を経て v0.13.0 で完済。

利用者は以下に移行する:

| 用途 | 移行先 |
|---|---|
| 1 サンプル遅延 (`y[k+1] = u[k]`) | `pyflw.blocks.UnitDelay` |
| Simulink ZOH 互換 (`y(t_k) = u(t_k)` 即時反映) | `pyflw.blocks.ZeroOrderHoldDirect` |

`pyflw.blocks.ZeroOrderHold` を import するコードは `ImportError` で失敗、
JSON モデルファイルで `"type": "pyflw.blocks.discrete.ZeroOrderHold"` を含む
ものは load 時に `UnknownBlockTypeError` で失敗する。`.flw.json` schema は
0.6 のまま (= type_path 削除は構造変更でない、ADR-0033 §2-A)。

### Compat / Risks

- pytest 949 件 (= v0.12.0 の 958 件から ZOH legacy テスト 9 件削除分の純減)、
  vitest 193 件 全 pass。
- mypy --strict / ruff / Sphinx warnings-as-errors clean。
- bundle gzip 185.78 KB (= v0.12.0 と同等、`ZeroOrderHoldGlyph` SVG 削除分は
  わずかに減少)。
- `examples/spring_mass_damper.py` 出力数値完全不変 (Final x=0.2505,
  x_dot=0.0031)。
- 本リリースで pyflw が **PyPI で初公開** される (`pip install pyflw==0.13.0`)。
  以後の release は GitHub Actions が自動 publish する (Trusted Publishers OIDC)。

## [0.12.0] - 2026-05-08

**Phase 4 完了タグ (release)**。ADR-0025 §(7) のリリース判定基準を満たす:

- ADR-0026 (model linearization, v0.10.0)
- ADR-0027 (frequency response + stability analysis, v0.10.1)
- ADR-0028 (Block registry i18n, v0.11.0)
- ADR-0029 (.flwlib.json library file format, v0.11.1)
- ADR-0030 (global toast + a11y aria-label i18n polish, v0.11.2)

すべて Accepted で実装済み、Phase 4 候補項目のうち PyPI 自動化 (E1) と
ダークモード (E2) は事前合意済の Phase 5+ 送り。本タグは **コード変更ゼロの
release commit** で、Phase 5 着手前の安定版マーカーとして機能する。

### Phase 4 で達成した機能 (ADR-0025 §(7) 判定基準)

- **解析機能**: 線形化 (central / forward 差分による Jacobian)、状態空間 (A,B,C,D)、
  Bode / Nyquist (python-control 経由 + numpy fallback)、固有値 / 根軌跡 / 安定性判定。
  `examples/pid_bode.py` で実例を配信。
- **Block 翻訳 (C1)**: `display_name` / `docstring_summary` の ja/en 両対応、REST schema
  `blocks.v2`、frontend client-side selection (`<30ms` 切替)。
- **`.flwlib.json` 配布 (C2)**: マスク Subsystem 集合の JSON 配布、組み込み 3 entry
  (PID + 1次/2次 plant)、Inline 配置で `.flw.json` 自己完結性を維持。
- **エラー toast (C3)**: グローバル Zustand store + `<ToastContainer>`、severity 4 種
  + WAI-ARIA 準拠の `role` / `aria-live`。
- **aria-label 網羅 (C4)**: ADR-0024 / ADR-0028 / ADR-0030 で UI chrome 全域カバー。

### 検証

- pytest 957 件 / vitest 193 件 全 pass
- mypy --strict / ruff / Sphinx warnings-as-errors clean
- frontend bundle 185.78 KB gzip (ADR-0023 §予算 1 MB の 18.6%)
- 数値完全不変: `examples/spring_mass_damper.py` の出力 (`Final x=0.2505,
  x_dot=0.0031`) は Phase 1 v0.1.0 から不変

### Phase 5 への持ち越し

- A4 (Python コード生成、numba/cython JIT)
- A5 (GPU バックエンド、jax / cupy / numba.cuda 選定)
- B1 (RateTransition、Simulink 同名)
- B2 (Triggered subsystem、可変ステップ離散)
- E1 (PyPI 公開自動化)
- E2 (ダークモード)
- E3 (追加言語 zh / ko / ar、RTL)
- E4 (Settings panel)
- ZeroOrderHold (legacy) の deprecation cycle 完了 (= 削除)

詳細は SPEC-0001 §機能要件 Phase 5 を参照。

## [0.11.2] - 2026-05-08

ADR-0030: グローバル toast 通知機構 + a11y aria-label 国際化総仕上げ。
Phase 4 sub-ADR #5 (= **Phase 4 sub-ADR の最終枠**)。`DiagramCanvas.tsx`
ローカル実装 (`useState<string|null>` + `setTimeout`) を全画面共通の Zustand
store + `<ToastContainer>` (App ルート mount) に置き換え、severity
(info / success / warning / error) ごとに ARIA role と aria-live を出し分ける。
最大 3 件 stacking、新着が画面下中央に積み重なる。close ボタンで manual
dismiss も可能。これにより v0.12.0 (Phase 4 完了タグ) のリリース判定基準
(ADR-0025 §(7)) を満たす。

### Added — Frontend

- `pyflw/web/frontend/src/store/toastStore.ts`: Zustand store。
  `pushToast({severity, message, durationMs?})` / `dismissToast(id)` /
  `clearAllToasts()` API。auto-dismiss timer を store 内で管理 (= memory
  leak 防止)、最大 3 件 stacking で超過時は最古を即時 dismiss。
- `pyflw/web/frontend/src/components/Toast.tsx`: `<ToastContainer>` +
  `<ToastView>`。severity 別の色 / icon / a11y 属性 (info/success →
  `role=status` / `aria-live=polite`、warning/error → `role=alert` /
  `aria-live=assertive`)。`<App>` ルートに 1 つ mount。
- i18n locale: `toast.region` / `toast.dismiss` を ja/en に追加。

### Changed

- `pyflw/web/frontend/src/components/DiagramCanvas.tsx`: ローカル `toast`
  state + 専用 `<div role="alert">` を削除。`showToast(msg)` ヘルパは
  `pushToast({severity:"warning", message:msg})` に置換 (port 形状エラー
  / connect 失敗 / library drop 失敗の 3 箇所が対象)。
- `pyflw/web/frontend/src/App.tsx`: ルート末尾に `<ToastContainer />` を mount。

### Tests

- `pyflw/web/frontend/tests/toastStore.test.ts` (13 件): push 動作 /
  severity デフォルト / auto-dismiss (info=3s, warning/error=5s) /
  durationMs=0 永続表示 / stacking 上限 / dismissToast / clearAllToasts /
  timer leak 防止 (drop 後に再 dismiss が走らない)。
- `pyflw/web/frontend/tests/Toast.test.tsx` (9 件): render が空のとき
  region 不在 / region に i18n aria-label / severity 別 role+aria-live /
  複数 toast の DOM 順 / 個別 close ボタンの a11y label と動作。

### Compat / Risks

- 純フロントエンド改修 (Python 側無変更)。
- `.flw.json` schema 0.6 / `.flwlib.json` schema libraries.v1 ともに無変更。
- 既存 pytest 957 件 / vitest 171 件は全 pass を維持しつつ、frontend +22 件で
  合計 193 件に増加。bundle gzip 増分 ≤ 1 KB。

## [0.11.1] - 2026-05-08

ADR-0029: ブロックライブラリファイル `.flwlib.json` フォーマット。Phase 4
sub-ADR #4 — マスク Subsystem 集合を JSON ファイルとして配布する仕組み。
組み込み `std.flwlib.json` (PID コントローラ + 1 次遅れプラント + 2 次プラント
の 3 entry、約 9.6 KB) を wheel に bundle し、サーバ起動時に
`/api/v1/libraries` 経由で frontend に提供する。GUI のパレットには既存の
Block class 一覧の **下** に Libraries セクションが追加され、drag&drop で
**Inline 配置** (= drop 瞬間に subsystem 定義をモデル本体にコピー、
`.flw.json` の自己完結性を維持) する。Subsystem のモデル schema (0.6) は
無変更、純粋に新 schema `libraries.v1` の追加。

### Added — Python libraries package

- `pyflw/libraries/__init__.py`: `Library` / `LibraryEntry` (frozen dataclass)、
  `load_library(path)` / `validate_library(data)` /
  `export_subsystem_to_library(subsystem, path, *, library_metadata,
  entry_metadata, append=True)`。
- `pyflw/libraries/_loader.py`: `CURRENT_LIBRARY_SCHEMA_VERSION =
  "libraries.v1"`、`SUPPORTED_LIBRARY_SCHEMA_VERSIONS`、空の
  `_LIBRARY_MIGRATIONS` registry (Phase 5+ で v2 を導入する際の枠)。
- `pyflw/libraries/std.flwlib.json`: 組み込みライブラリ 3 entry
  (`pid_controller` / `first_order_plant` / `second_order_plant`)。
  Mask placeholder (`$Kp` / `$Ki` / `$Kd` / `$tau` / `$K` / `$a` / `$b`)
  でパラメトリゼーション、`Subsystem.to_dict()` と byte-identical。
- `pyflw/server/library_registry.py`: `build_library_registry(library_paths,
  *, bundle_builtin=True)` で起動時に `Settings.library_paths` + 組み込み
  std を一括 load。1 ファイル不正でも他は継続 (= `LibraryLoadError` に記録)、
  library 名の重複は先勝ち + warning。
- `pyflw/server/routes/libraries.py`: REST 2 endpoint。`GET /api/v1/libraries`
  は subsystem body を含めない一覧 (= ペイロード削減)、`GET /api/v1/libraries/
  {lib}/{entry}` は subsystem body 同梱の詳細。
- `pyflw/exceptions.py`: `LibraryFileError`、`LibraryEntryNotFoundError`。
- `pyflw/server/settings.py`: `library_paths: list[Path]` /
  `bundle_builtin_libraries: bool = True`。
- `tools/build_std_library.py`: 組み込み `std.flwlib.json` のジェネレータ
  (= `Subsystem._from_dict` → `to_dict` で round-trip 後にディスクへ書く、
  byte-identical 保証)。

### Added — Frontend

- `pyflw/web/frontend/src/types/api.ts`: `LibraryEntryMetadata` /
  `LibraryMetadata` / `LibraryRegistryResponse` / `LibraryEntryDetail` /
  `LibraryLoadError` 型。
- `pyflw/web/frontend/src/api/client.ts`: `listLibraries()` /
  `getLibraryEntry(library, entry)`。
- `pyflw/web/frontend/src/lib/blockI18n.ts`: `localizeName<T>` /
  `localizeDescription<T>` (generics 化)。`localizedDisplayName` (Block 専用、
  type_path フォールバック付き) は既存 callers の互換のため別関数として残す。
- `pyflw/web/frontend/src/components/BlockPalette.tsx`: Libraries セクション
  追加。組み込みカテゴリと並列に `library.<name>` 単位で折りたたみ表示、
  drag-start で `application/pyflw-library-entry-ref` MIME に
  `{library, entry}` を運ぶ。
- `pyflw/web/frontend/src/components/DiagramCanvas.tsx`: drop 経路で先に
  `application/pyflw-library-entry-ref` を check し、`getLibraryEntry()` で
  body を fetch → ID 採番後に `addBlockToEditing` で Inline 展開する。
- i18n locale: `palette.library_prefix` / `diagram.library_drop_invalid_ref`
  / `diagram.library_drop_failed` を ja/en に追加。

### Tests

- `tests/libraries/test_loader.py` (8 件): 最小有効 / schema_version 不正 /
  必須キー欠落 / migration registry 空 / 組み込み std bundle / Subsystem 以外
  type 拒否 / 重複 entry id 拒否。
- `tests/libraries/test_registry.py` (5 件): 複数 path / invalid file 耐性 /
  bundle_builtin / ディレクトリ再帰 / 重複 library 名先勝ち。
- `tests/libraries/test_export.py` (4 件): 新規 export / append / 重複 id 拒否
  / round-trip byte-identical。
- `tests/server/test_libraries_route.py` (5 件): list schema_version /
  body 省略 / 詳細取得 + 再構築可 / 404 / `/blocks` への影響なし。
- `pyflw/web/frontend/tests/libraryI18n.test.ts` (10 件): generics 関数の
  フォールバック chain。
- `pyflw/web/frontend/tests/libraryDragDrop.test.ts` (5 件): MIME ペイロード
  契約 + `getLibraryEntry` API 経路 + Inline placement の不変条件。

### Compat / Risks

- `.flw.json` schema 0.6 は無変更 (= 既存モデルファイル全てそのままロード可)。
- 組み込み 3 entry はすべて `Subsystem._from_dict()` で再構築でき、
  `examples/spring_mass_damper.py` の出力数値も完全不変。
- 既存 pytest 933 件 + vitest 156 件は全 pass を維持しつつ、Python +22 件 /
  frontend +15 件で合計 955 + 171 件に増加。

## [0.11.0] - 2026-05-08

ADR-0028: Block class registry の i18n 化。Phase 4 sub-ADR #3 — built-in
の 35 ブロック全てに ja/en 翻訳テーブルを追加し、REST レスポンスに
`display_name_i18n` / `docstring_summary_i18n` フィールドを同梱する。
Frontend は registry を 1 回 fetch して、言語切替時にクライアント側で
表示文字列を選び替える (= 再 fetch なし、<30ms 切替)。ADR-0024 で残って
いた「UI chrome は ja、ブロック名は en」というハイブリッド表示が解消され、
日本語環境では palette / QuickAdd 等で「定数」「加算」「積分器」のように
表示されるようになる。

### Added — Python registry

- `pyflw/server/registry_translations.py`: ADR-0028 集中翻訳テーブル
  (`_BLOCK_TRANSLATIONS`、35 type_path × ja/en × {display_name,
  docstring_summary})。`Locale` 型 / `SUPPORTED_LOCALES` /
  `get_translations(type_path)` / `all_registered_type_paths()` を export。
- `BlockMetadata` dataclass に `display_name_i18n: dict[str, str]` /
  `docstring_summary_i18n: dict[str, str]` を追加 (`field(default_factory=dict)`、
  3rd-party 拡張で未登録 type_path は空 dict)。
- `tests/server/test_registry_translations.py`: 翻訳カバレッジ + フォーマット
  + `build_metadata` / `metadata_to_dict` の round-trip を検証する 80 件
  (parametrize 展開後)。
- `tests/server/test_blocks_registry.py`: ADR-0028 用に 3 件追加 (i18n
  カバレッジ、後方互換、Constant の ja 翻訳)、既存 1 件を `blocks.v2` 用に更新。

### Added — Frontend

- `pyflw/web/frontend/src/lib/blockI18n.ts`: `localizedDisplayName` /
  `localizedDocstringSummary` / `searchableDisplayNames` の 3 ヘルパー。
  フォールバック chain は `i18n[lang]` → `display_name` → `type_path`
  (= 3rd-party 旧サーバ互換)。
- `pyflw/web/frontend/tests/blockI18n.test.ts`: 10 件の vitest ケース。

### Changed

- `pyflw/server/registry.py`: `build_metadata()` で `get_translations()` を
  読み、`display_name` / `docstring_summary` を `_BLOCK_TRANSLATIONS["..."]
  ["en"]` 値で **正規化** (= 既存 `_BUILTIN_METADATA` の手書き en と
  registry_translations の en が必ず一致するようにする)。`metadata_to_dict()`
  に `display_name_i18n` / `docstring_summary_i18n` を同梱。
- `pyflw/server/routes/blocks.py`: `GET /api/v1/blocks` レスポンスの
  `schema_version` を `"blocks.v1"` → `"blocks.v2"` に bump。
  `supported_locales: ["en", "ja"]` を追加。
- `pyflw/web/frontend/src/types/api.ts`: `Locale = "en" | "ja"` 型追加、
  `BlockMetadata` に `display_name_i18n?` / `docstring_summary_i18n?` (optional)、
  `BlockRegistryResponse` に `supported_locales?` (optional)。旧 frontend
  / 旧サーバ間の混在で壊れない。
- `pyflw/web/frontend/src/components/BlockPalette.tsx`,
  `QuickAdd.tsx`: 表示文字列を `localizedDisplayName(b)` /
  `localizedDocstringSummary(b)` 経由に置換。検索フィルタは
  `searchableDisplayNames(b)` の両言語インデックスで動作 (= ja 環境でも
  `"sum"` で `"加算"` がヒット、Simulink 経験者向けセーフネット)。
- `pyflw/__init__.py.__version__`、`pyproject.toml.version`、
  `pyflw/web/frontend/package.json` を `0.11.0` に bump。

### Acceptance criteria (ADR-0028 §(8))

- 35 built-in blocks に ja/en 両方の `display_name` / `docstring_summary`
  が登録されている — `tests/server/test_registry_translations.py::
  TestTranslationCoverage` で継続検証。
- `display_name` / `docstring_summary` は en コピーで後方互換維持 —
  `tests/server/test_blocks_registry.py::test_legacy_fields_match_en_translation`
  で検証。
- 言語切替が registry 再 fetch を起こさない (`localizedDisplayName` の
  クライアント側選択)。
- pytest 933 pass (851 baseline + 82 new)、vitest 155 pass (145 baseline +
  10 new)、mypy --strict / ruff / sphinx -W clean。
- `examples/spring_mass_damper.py` 数値完全不変 (`Final x=0.2505,
  x_dot=0.0031`)。

### Phase 4 status

ADR-0025 §(1) #4 (C1) is now `Accepted (v0.11.0)`. Next up: ADR-0029
(C2 `.flwlib.json` library file format) and ADR-0030 (C3 toast + C4
a11y), heading to the Phase 4 closure tag at `v0.12.0`.

## [0.10.1] - 2026-05-07

ADR-0027: frequency response (Bode / Nyquist) and stability analysis
(eigenvalues, ``is_stable``, root locus). Phase 4 sub-ADR #2 — adds a
thin layer of analysis helpers on top of :class:`pyflw.LinearSystem`
from ``v0.10.0``. ``eigenvalues`` and ``is_stable`` are numpy-only and
work without the ``pyflw[control]`` extra; ``bode`` / ``nyquist`` /
``root_locus`` delegate to ``python-control`` and require the extra.

### Added — `pyflw.analysis`

- `pyflw/analysis/frequency_response.py`: :func:`pyflw.bode` /
  :func:`pyflw.nyquist` and the corresponding :class:`BodeResponse` /
  :class:`NyquistResponse` frozen dataclasses (matching the
  :class:`LinearSystem` pattern: numpy arrays + labels +
  ``plot(ax, show)``). Magnitude / phase / response are 3-D arrays
  shaped ``(p, m, n_omega)`` to match ``python-control`` 0.10.
- `pyflw/analysis/stability.py`: :func:`pyflw.eigenvalues`,
  :func:`pyflw.is_stable`, :func:`pyflw.root_locus`, and the
  :class:`RootLocus` dataclass. ``is_stable`` follows ADR-0027 §(6) —
  strict ``Re(λ) < -tol`` (default ``tol=1e-9``), so marginal /
  imaginary-axis poles count as **unstable**. ``root_locus`` extracts
  a SISO sub-system from a MIMO :class:`LinearSystem` via
  ``input_idx`` / ``output_idx`` (ADR-0027 §(7)).
- :class:`LinearSystem` gains ``bode`` / ``nyquist`` /
  ``eigenvalues`` / ``is_stable`` / ``root_locus`` instance methods
  (lazy-imported delegations, same pattern as ``Simulator.linearize``
  in ADR-0026).
- 31 new pytest cases (`tests/analysis/test_frequency_response.py`
  + `tests/analysis/test_stability.py`) covering Integrator,
  TransferFunction, second-order resonance, Nyquist locus shape,
  marginal stability of pure-imaginary poles, custom ``tol``,
  ``input_idx`` / ``output_idx`` validation, and matplotlib ``plot``
  smoke tests with the Agg backend.
- `examples/pid_bode.py`: PI + 1st-order plant feedback loop
  linearised, eigenvalue + Bode rendering example.
- `docs/analysis.rst`: Sphinx page extended with the new helpers and
  their result types.

### Changed

- Top-level `pyflw` package re-exports the new functions and
  dataclasses (`bode`, `nyquist`, `eigenvalues`, `is_stable`,
  `root_locus`, `BodeResponse`, `NyquistResponse`, `RootLocus`).
- :class:`LinearSystem.to_control_ss` docstring example refreshed to
  ``ls.bode().plot()`` (the new direct path).
- `pyflw/__init__.py.__version__`, `pyproject.toml.version`, and
  `pyflw/web/frontend/package.json` bumped to ``0.10.1``.

### Acceptance criteria (ADR-0027 §(10))

- Integrator Bode magnitude / phase match analytical 1/ω, -π/2
  within ``rtol=1e-4``.
- 1st-order LPF magnitude / phase match
  ``1/sqrt(1+ω²)`` / ``-atan(ω)`` within ``rtol=1e-4``.
- 2nd-order resonance peak ``1/(2ζ√(1-ζ²))`` within ``rtol=1e-3``.
- Diagonal LTI eigenvalues within ``rtol=1e-12`` (LAPACK ``geev``).
- Pure-imaginary poles → ``is_stable = False`` (ADR-0027 §(6)).
- pytest 848 pass (817 baseline + 31 new), mypy --strict clean,
  ruff clean, sphinx ``-W`` warning-free.
- ``examples/spring_mass_damper.py`` numerics unchanged
  (``Final x=0.2505, x_dot=0.0031``).

### Phase 4 status

ADR-0025 §(1) #2 (A2 frequency response) and #3 (A3 stability) are
now ``Accepted (v0.10.1)``. Next up is the GUI extension chain —
ADR-0028 (Block registry i18n), ADR-0029 (`.flwlib.json` library
files), ADR-0030 (toast + a11y) — heading toward the Phase 4 closure
tag at ``v0.12.0``.

## [0.10.0] - 2026-05-07

ADR-0026: model linearisation. First sub-ADR of **Phase 4** (analysis
+ codegen + GPU + GUI extensions). Adds a numerical-Jacobian
linearisation API that returns the state-space :math:`(A, B, C, D)`
matrices around an operating point.

### Added — `pyflw.analysis`

- `pyflw/analysis/__init__.py`, `pyflw/analysis/linearize.py`: new
  package providing :func:`pyflw.linearize` and the
  :class:`pyflw.LinearSystem` dataclass. Both are re-exported from the
  top-level `pyflw` namespace.
- :func:`pyflw.linearize` `(simulator, *, t=0.0, x=None, u=None,
  method="central", epsilon=None) -> LinearSystem`. ``method="central"``
  uses central differences (error :math:`O(h^2)`),
  ``method="forward"`` uses forward differences (error :math:`O(h)`,
  half the cost). ``method="jax"`` is reserved for Phase 5+ and raises
  :class:`NotImplementedError` for now.
- :class:`pyflw.LinearSystem` (``@dataclass(frozen=True, eq=False)``)
  with ``A / B / C / D`` matrices, ``state_names``, ``input_names``,
  ``output_names`` (each port flattened C-order, with
  ``"{block_id}.x[{i}]" / ".in[{port_idx}][{flat_idx}]" /
  ".out[{port_idx}][{flat_idx}]"``), ``operating_point``, and
  :meth:`LinearSystem.to_control_ss` for handing the result to
  ``python-control``.
- :meth:`pyflw.Simulator.linearize` thin wrapper.
- New ``pyflw[control]`` extras (`control >= 0.10`) for
  ``to_control_ss``. Added to `dev` extras as well so CI runs that
  test path.
- `tests/analysis/`: 80 new pytest cases (test-writer reinforced)
  covering Integrator, StateSpace, TransferFunction,
  MimoTransferFunction, PI + 1st-order plant feedback (2 continuous
  states), Subsystem flattening, SM-B (Mux/Demux + Integrator), edge
  cases (pure-discrete rejection, hybrid warning, invalid shape
  errors, ``jax`` not-implemented, ``epsilon`` precision gradient,
  NaN/Inf operating point, Saturation operating-point dependence),
  the ``to_control_ss`` round-trip, dimension corner cases (zero
  inputs / zero outputs / 1×1×1), and the ``LinearSystem`` dataclass
  contract (frozen, ``eq=False``, label uniqueness).
- `docs/analysis.rst`: Sphinx page introducing `pyflw.linearize` and
  the `python-control` integration. Linked from `docs/index.rst`.

### Changed

- `pyflw/__init__.py`: now also exports `linearize` and `LinearSystem`.
- `pyflw/core/simulator.py`: adds ``Simulator.linearize`` method (thin
  delegating wrapper). No change to the existing `_step` /
  `_step_vector` / `run` hot paths — `linearize` re-implements a
  side-effect-free version of the output passes inside
  `pyflw.analysis.linearize._evaluate`.
- `pyproject.toml`: ``mypy.overrides`` now also ignores ``control.*``.

### Acceptance criteria (ADR-0026 §(13))

- Integrator: ``A=[[0]], B=[[1]], C=[[1]], D=[[0]]`` to ``atol=1e-12``.
- StateSpace: round-trip identity to ``rtol=1e-9``.
- TransferFunction (1st / 2nd order): companion form match to
  ``rtol=1e-4``.
- PI controller + 1st-order plant feedback loop: 2 continuous states
  extracted (Integrator + Plant), A/B/C/D shapes consistent with the
  system topology.
- pytest 817 pass (737 baseline + 80 new analysis), mypy --strict
  clean, ruff clean, sphinx ``-W`` warning-free.
- `examples/spring_mass_damper.py` numerics unchanged
  (`Final x=0.2505, x_dot=0.0031`).

### Phase 4 status

ADR-0025 §(1) #1 (A1) is now ``Accepted (v0.10.0)``. Next up are
A2/A3 (Bode/Nyquist + stability analysis, ADR-0027) and the GUI i18n
extension chain (C1–C4, ADR-0028 onwards).

## [0.9.0] - 2026-05-07

**Phase 3 complete.** No code changes since v0.8.1 — this release is the
SemVer milestone marking the close of Phase 3 of the roadmap
(SPEC-0001 §機能要件 Phase 3, ADR-0016).

### Phase 3 in summary

ADR-0016 (Phase 3 全体方針) chose to clear the Phase 2 backlog before
moving on to analysis / codegen / GPU. The eight sub-ADRs that follow
were all Accepted and shipped between v0.5.0 and v0.8.1:

| ADR | tag | scope |
|---|---|---|
| ADR-0014 | v0.3.0 | Simulator update timing fix (BREAKING) |
| ADR-0015 | v0.4.0 | UnitDelay 2-state augmentation refactor (BREAKING) |
| ADR-0017 | v0.6.0 | SM-B vector ports + Block API extension (BREAKING) |
| ADR-0018 | v0.6.1 | Mux / Demux + SM-B run path |
| ADR-0020 | v0.6.2 | JSON schema 0.5 layout persistence |
| ADR-0019 | v0.7.0 | GUI drag-drop + palette + Block class registry |
| ADR-0021 | v0.7.1 | Subsystem drilldown + mask parameters (schema 0.6) |
| (—) | v0.7.2 | GUI polish (Display / XYGraph, dynamic ports, resize, multi-select) |
| ADR-0023 | v0.8.0 | uPlot Scope + SoA ScopeBuffer (BREAKING for ScopeBuffer consumers) |
| ADR-0024 | v0.8.1 | Web GUI i18n (ja / en) via react-i18next |

### SPEC-0001 revision

`.claude/docs/specs/0001-pyflw-overview-and-roadmap.md` is rewritten:

- §機能要件 Phase 3 is replaced with the actual delivered set
  (#15-#25, mapping to ADR-0014/15/17–24).
- §機能要件 Phase 4 collects the SPEC-original #16-#21 (block library
  files, linearisation, frequency response, stability analysis,
  codegen, GPU) and the items that ADR-0016 §(2) explicitly punted
  (RateTransition, Triggered subsystems, block `display_name`
  translation, error toast i18n, a11y aria-label).
- §機能要件 Phase 5+ collects the items the user pulled out of
  Phase 3 scope (PyPI automation, dark mode) plus other
  later-phase work (additional languages, settings panel, 3D
  animation, optimisation solver, parameter sweep).
- §未決事項 reflects which Phase 3 ADRs resolved which entries.
- §変更履歴 has a 2026-05-07 entry summarising the closure.

### Carried into Phase 4 (next)

ADR-0025 (Phase 4 overview) will be drafted next to declare:

- Sub-ADR slots for #26 (linearisation), #29 (codegen), #30 (GPU).
- The ordering: SM-B is now stable, so `Jacobian` API design can
  proceed without rework risk.
- Versioning plan: minor bumps per major capability (linearisation
  v0.10.0, codegen v0.11.0, GPU v0.12.0; all subject to ADR-0025
  reordering).
- Phase 5+ deferral reaffirmed: PyPI automation, dark mode,
  additional languages, settings panel.

### Unchanged

- `pyflw/__init__.py.__version__` and `pyproject.toml.version` bumped
  to `0.9.0`. No source code changes between v0.8.1 and v0.9.0.
- All tests still pass (Python pytest 737, frontend vitest 145).
- All Python and frontend dependencies unchanged from v0.8.1.

## [0.8.1] - 2026-05-07

ADR-0024: Web GUI internationalisation (i18n / ja-en). The UI chrome
(menu, toolbar, palette, quick-add, status bar, modals, parameter
panel, breadcrumb, scope placeholders, diagram error overlays) is now
served through `react-i18next` with flat dot-notation JSON
dictionaries. Block `display_name` / `docstring_summary` and error
toasts remain English (Phase 4 — separate ADR will tackle Python
registry-side translation).

This release closes Phase 3 of the roadmap (ADR-0016): all Phase 3
sub-ADRs (0017–0024) are now Accepted and shipped. C1 (PyPI
automation) and C3 (dark mode) were re-classified to Phase 5+ per user
request and are not blockers for the next phase.

### Added

- `pyflw/web/frontend/src/i18n/index.ts`: i18next + react-i18next init
  with `localStorage["pyflw.lang"]` persistence and
  `navigator.language` startup detection (`ja*` → `ja`, otherwise
  `en`).
- `pyflw/web/frontend/src/i18n/locales/{en,ja}.json`: 99 translation
  keys covering every UI chrome surface.
- `pyflw/web/frontend/src/i18n/types.d.ts`: i18next module
  augmentation so `t()` is typed against the en.json shape.
- `View > Language ▸ English / 日本語` submenu with a checkmark on the
  active language. Switching is immediate and persists across reloads.
- `tests/i18n.test.ts`: 12 vitest cases (key set parity ja vs en,
  non-empty values, lookup, language switch, interpolation,
  localStorage persistence, invalid-language guard).
- Runtime deps: `i18next ^23.16.8`, `react-i18next ^14.1.3` (the
  versions ADR-0024 §Decision §(1) targeted; later majors give the
  same gzipped footprint within ±1 KB). No build-time Babel macro /
  generator — the chosen stack is purely runtime + JSON imports per
  ADR-0024 §Decision §(2).

### Changed

- `MenuBar`, `Toolbar`, `BlockPalette`, `QuickAdd`, `StatusBar`,
  `TabStrip`, `Modal` (Open / Rename / Confirm), `App.EmptyState` and
  panel headers, `SimulationControls`, `ParameterPanel` (regular +
  mask editor), `Breadcrumb`, `DiagramCanvas` overlays, `ScopeView`
  empty placeholder, `XYGraphView` empty placeholder are wired through
  `useTranslation()`.
- `main.tsx` imports `./i18n` synchronously before the React tree
  mounts (no FOUC; SPA-only, no SSR).

### Acceptance criteria (ADR-0024 §11)

- ja and en dictionaries have identical key sets — enforced by
  `i18n.test.ts` (`Object.keys(ja).sort() === Object.keys(en).sort()`).
- Bundle size budget: target ≤ +15 KB gzip / measured **+20.61 KB JS
  gzip + 0.02 KB CSS gzip**. ADR-0024 §11.note documents a minor
  revise that relaxes the soft target to <25 KB and the
  re-evaluation trigger to >30 KB. The Phase 3 hard ceiling
  (1 MB gzip per ADR-0016 §Risks #6) is not affected — total bundle
  is now 184.57 KB JS + 7.62 KB CSS gzip.
- Initial paint: synchronous `i18next.init` keeps language stable on
  first frame; no flash of untranslated content.

### Phase 4 send-offs (per ADR-0024)

- Block `display_name` / `docstring_summary` translation (needs a
  Python-side registry change).
- Error toast / API error i18n (no toast surface yet — added together
  with the future toast component).
- Settings panel for language selection (View menu is sufficient for
  v0.8.1).
- Additional languages (zh / ko / ar) + RTL.
- ICU MessageFormat (added on demand via `i18next-icu`).
- Python-side log / exception localisation.

### Unchanged

- WebSocket and REST schemas, `.flw.json` format, simulation
  semantics, Python tests (737 pytest pass), `examples/spring_mass_damper.py`
  output (`Final x=0.2505, x_dot=0.0031`).

## [0.8.0] - 2026-05-07

Two themes:

1. **ADR-0023**: Scope rendering performance. Replaces the hand-rolled
   canvas 2D plot with [uPlot](https://github.com/leeoniya/uPlot) and
   rebuilds the in-memory `ScopeBuffer` as Structure-of-Arrays
   (`Float64Array` per signal) with a doubling ring buffer. Long
   simulations no longer suffer the O(N²) append cost that came from
   `[...arr, ...batch]` spreading on every WebSocket frame. Wire format
   (`scope_batch` `number[][]`) is unchanged — the SoA conversion is
   purely a frontend boundary detail.
2. **Phase 3 GUI polish**: Simulink-style keyboard shortcuts, a
   double-click "quick insert" popup, Ctrl-drag (in addition to
   right-drag) for block duplication, and a fix for Subsystems whose
   default `params.blocks` was the registry's `null` (not the empty
   array).

### Added — Scope rendering (ADR-0023)

- `pyflw/web/frontend/src/lib/scopeBuffer.ts`: column-major SoA buffer
  with `createBuffer()` / `appendBatch()` and amortized O(1) append.
- `pyflw/web/frontend/src/components/UPlotChart.tsx`: minimal uPlot
  React wrapper (no `uplot-react` dependency). Mounts uPlot once,
  `setData` on data prop change, ResizeObserver-driven `setSize` on
  parent size change, `destroy()` on unmount.
- `tests/scopeBuffer.test.ts`: 27 new vitest cases covering capacity
  doubling at the 1024-boundary, transposition (wire row-major → SoA
  column-major), batch rejection on `n_signals` mismatch, NaN /
  Infinity / -0 storage, 50000-point single batch (multi-stage
  doubling), reference stability for in-capacity appends, and a
  100k-point linear-time smoke.
- `tests/uPlotChart.test.tsx`: 8 new vitest cases (mount, unmount,
  setData on data change, no setData on identical reference, options
  reference change → destroy + rebuild, options-change-with-stable-data
  doesn't double-call setData, className prop wiring, double-unmount
  protection) using `@testing-library/react` + jsdom.
- `tests/displayLiveValue.test.tsx`: 18 new vitest cases for the
  `Display` block live readout (extracted last sample from each SoA
  column, formatter behaviour for exponential / fixed / NaN / Infinity).
- `uplot ^1.6.32` runtime dependency. Devs: `jsdom`,
  `@testing-library/react`.

### Added — Editor shortcuts and polish

- `pyflw/web/frontend/src/components/QuickAdd.tsx`: fuzzy block search
  popup. Trigger by double-clicking on the empty pane; arrow keys
  navigate, Enter inserts at the cursor position, Esc closes. Position
  is clamped against all four window edges.
- `pyflw/web/frontend/src/lib/useShortcuts.ts`: Simulink-style global
  shortcuts wired in `App.tsx`:
  - **Ctrl+T / F9**: run simulation (Ctrl+T may be hijacked by the
    browser as "open new tab"; F9 is the reliable alias).
  - **Ctrl+Shift+T / Shift+F9**: stop simulation.
  - **Ctrl+A**: select all blocks + edges in the current scope (skips
    when focus is on an `<input>` / `<textarea>` / contenteditable).
  - **Ctrl+C / Ctrl+V**: copy selection to in-memory clipboard / paste
    at +20px offset, new IDs auto-allocated, connections internal to
    the selection are preserved, clipboard payload survives
    drilldown-up but not page reload.
  - **Esc**: drill up one Subsystem level, or clear selection if at the
    top of the path.
  - **Enter**: drill down into the single selected `is_container`
    block (no-op otherwise).
- `pyflw/web/frontend/src/components/DiagramCanvas.tsx`:
  **Ctrl+left-drag** (in addition to **right-drag**) on a block now
  duplicates it and follows the cursor — Simulink's two-button
  duplicate. Listener is registered with capture on both `mousedown`
  and `pointerdown` so React Flow's internal drag does not start on
  the original node.
- `pyflw/web/frontend/src/components/Toolbar.tsx`: tooltips updated to
  show the new shortcuts.

### Fixed — Subsystem with null inner blocks (regression from v0.7.2)

- `pyflw/web/frontend/src/lib/idGenerator.ts`: `buildDefaultParams`
  now accepts an `{ isContainer }` option and injects
  `blocks: []` / `connections: []` for `is_container=true` blocks,
  even when the registry returns the Python-side default of `null`
  (`Subsystem.__init__(blocks: list[Block] | None = None)`).
- `pyflw/web/frontend/src/lib/pathResolver.ts`:
  `resolveBlocksAtPath` and `applyAtPath` now coerce `null` /
  `undefined` `params.blocks` / `params.connections` / `params.layout`
  to empty array / dict, rescuing existing models that were saved
  with the buggy shape. A truly non-Subsystem block (no `blocks` key
  at all) still throws as before.
- `pyflw/web/frontend/src/components/BlockPalette.tsx` and
  `QuickAdd.tsx` pass `isContainer` to `buildDefaultParams`.
- `tests/pathResolver.test.ts`: regression test for null `blocks` /
  `connections` rescue (`+1` case).

### Changed — Frontend (BREAKING for `ScopeBuffer` consumers)

- `pyflw/web/frontend/src/store/appStore.ts`: `ScopeBuffer` is now
  `{ times: Float64Array; values: readonly Float64Array[]; length;
  capacity; n_signals }` (re-exported from `lib/scopeBuffer.ts`). Any
  external code reading `buffer.values[i][p]` (row-major) must switch
  to `buffer.values[p][i]` (column-major). All in-tree consumers
  (ScopeView, XYGraphView, BlockNodeView's Display) have been updated.
  `handleStreamMessage` now delegates to `appendScopeBatch` so the SoA
  append path is single-sourced.
- `pyflw/web/frontend/src/components/ScopeView.tsx`: completely
  rewritten on top of `UPlotChart`. Tailwind 8-color palette (sky,
  emerald, amber, rose, violet, cyan, lime, pink) rotates per signal
  index. Empty-buffer placeholder kept. `buildAlignedData` /
  `buildOptions` exposed under `@internal` for testing.
- `pyflw/web/frontend/src/components/XYGraphView.tsx`: still canvas
  self-rendered (uPlot requires monotonic X — parametric trajectories
  are out of scope per ADR-0023 §Decision §(2)). Updated to read SoA
  column slices `values[0]` (x) / `values[1]` (y).
- `pyflw/web/frontend/src/components/BlockNodeView.tsx` (Display block
  live readout): updated to extract last sample from each SoA column.
  `DisplayLiveValue` / `formatDisplayValue` exposed under `@internal`
  for testing.
- `pyflw/web/frontend/vitest.config.ts`: added `environment: "jsdom"`
  + setup file with a `ResizeObserver` polyfill stub.

### Acceptance criteria (ADR-0023 §Decision §(8))

- 100k points × 1 trace at 60 fps scroll
- 100k points × 4 traces at 30 fps
- Initial draw < 100 ms
- Heap stays under ~50 MB for the 100k-point window
- Bundle size budget: ≤ +25 KB gzip vs v0.7.2 — actual measured
  +25.07 KB gzip JS / +0.41 KB gzip CSS (well under the +37.5 KB
  re-evaluation trigger documented in ADR-0023 §再考トリガー).

### Unchanged

- WebSocket `scope_batch` wire format (`{ times: number[]; values: number[][] }`).
- Server-side Python (`pyflw/server/`): no changes.
- All Python tests, JSON schema, simulation semantics: unchanged.

## [0.7.2] - 2026-05-07

GUI polish iteration. No ADR-level architectural changes; this release
sands down the rough edges of v0.7.1 in response to interactive
feedback so the editor feels closer to a desktop simulation tool than a
generic web app. Schema, JSON wire format, runtime, and CLI behaviour
are unchanged (so v0.7.1 model files load identically).

### Added — Sinks

- `Display` block: live numerical readout drawn on the block face
  during simulation. Reuses Scope's WebSocket pipeline (duck-typed
  `record` / `times` / `values` / `labels`), so the server side is
  unchanged. Frontend renders the latest sample as a large monospaced
  number; configurable `decimals` and `n_inputs`.
- `XYGraph` block: parametric x-y scatter line. Two scalar inputs
  (`x`, `y`); same WebSocket pipeline; new `XYGraphView` component
  draws axes, polyline, and a marker on the latest point. `plot()`
  helper for CLI/pytest.
- 19 new `tests/blocks/test_display_xygraph.py` cases (defaults,
  validation, simulation round-trip, JSON persistence, registry
  membership).

### Added — Editor (visual / interaction)

- **Per-block shape system** (`lib/blockShapes.ts`): triangle (Gain),
  circle / pill (Sum, Product, Divide), bar (Mux, Demux), trapezoids
  (Inport / Outport), wide rect (TF, StateSpace, MIMO TF, Discrete
  TF/SS, Display). Compact rect (~72×40) for the rest. Block ID is
  rendered absolutely outside the React Flow node bounding box so it
  doesn't get covered by the resizer.
- **Per-block SVG glyph library** (`lib/blockGlyphs.tsx`): 35 hand-drawn
  glyphs (formulas, waveforms, switches, scope/screens, etc.). When a
  rect-shaped block has no primary parameter to display, the glyph is
  centered larger (so blocks like `Sign` / `Abs` / `Integrator` stop
  looking half-empty).
- **Dynamic port count** (`lib/dynamicPorts.ts`): the GUI now reads
  `Sum.signs` / `Product.n_inputs` / `Mux.n` / `Demux.n` / `MinMax.n_inputs`
  / `LogicalOperator.n_inputs` / `Scope.n_inputs` / `Display.n_inputs` /
  `Terminator.n_inputs` / `Subsystem.n_inputs/outputs` /
  `StateSpace.B.shape[1]` / `C.shape[0]` / `MimoTransferFunction.numerators`
  shape / `DiscreteStateSpace` matrix shape, and updates the visible
  handle count live as the user edits the parameter. Accompanied by
  19 unit tests in `tests/dynamicPorts.test.ts`.
- **Block size persistence** (ADR-0020 §(2) Phase-4 item brought
  forward): `LayoutEntry` gains optional `w` / `h`. `Subsystem` /
  `Simulator.save / load` / `normalize_layout` accept these fields.
  React Flow's `NodeResizer` is wired up — drag a corner to resize,
  size persists across reloads. Six new pytest cases in
  `tests/core/test_layout_persistence.py`.
- **Live resize / live drag**: `liveSize` state in `BlockNodeView`
  reflects every `onResize` event, so the SVG geometry of circles,
  triangles, and rects follows the cursor smoothly. Both
  `updateBlockPosition` (during node drag) and `updateBlockSize`
  (during resize) now fire on every frame, fixing the React Flow
  controlled-mode "snap-back to original on render" bug that previously
  made horizontal resize and node drag look like they failed.
- **NodeResizer dynamic port handling**: `useUpdateNodeInternals`
  refreshes React Flow's internal handle registry whenever `nIn` /
  `nOut` change, so handle dots actually move when the user changes
  port count. Block height grows automatically (`max(baseH, n*12+8)`)
  so 8 inputs no longer overlap; circles stretch to a pill shape.
- **Multi-selection** of nodes and edges: `selectedNodeIds` and
  `selectedEdgeIds` stores. Box selection (left-drag on empty pane,
  partial intersection mode) selects nodes and edges together. Shift /
  Ctrl / Cmd add to selection. `Backspace` / `Delete` removes everything
  selected.
- **Edge selection visibility**: removed inline edge `style` (which was
  beating the `.selected` CSS rule on specificity) and centralised the
  hover / selected stroke rules in `index.css`. Hovering an edge now
  shows it's clickable; selecting one tints it blue and adds a soft
  glow.
- **Right-click duplicate** (Simulink-style): right-click + drag on a
  node clones it (deep params copy, new auto-incremented `{TypeName}_{N}`
  id) and follows the cursor. Right-click drag on the empty pane still
  pans. OS context menu is suppressed inside the canvas.
- **Shift+drag = disconnect**: holding Shift while starting a node drag
  removes every edge connected to the selected nodes, matching Simulink.
- **Param panel covers more types**: numeric, string, and boolean
  parameters are all editable. `signs`, `operator`, `criterion` strings
  are exposed as text inputs. Edits commit on every keystroke (with
  type-aware coercion) so the canvas reflects port-count changes
  without waiting for blur.
- **Block dropping initial values**: the registry now folds
  `_default_factory_args` into `params_spec.default`, so dropping
  `Mux` / `Demux` / `Subsystem` / `TransferFunction` / `Inport` /
  `Outport` produces correct defaults (`n=2`, `n_inputs=1`, `numerator=[1.0]`,
  …) instead of the previous `0` / `null` placeholders.

### Changed — Layout & polish

- **Desktop-shell layout**: title bar + menu bar (File / Edit / View /
  Simulation / Help) + toolbar (Save / Undo / Redo / Zoom / Fit / Run /
  Stop) + tab strip + status bar. The old `Models` sidebar tab is
  gone — model open / save / rename / save-as / delete moved into the
  File menu and dialog modals. `useSimulation` hook centralizes
  start/stop + WebSocket lifecycle so the toolbar Run button feeds the
  same scope stream as the bottom progress bar.
- **Auto-layout**: horizontal-first grid (left → right, 8-wide before
  wrap) with tighter pitch, matching Simulink reading order.
- **Canvas chrome**: smooth-step edges by default, slate-toned stroke,
  thicker / glowing on hover and selection. MiniMap and Controls flat
  (no rounded shadow), system fonts (Segoe UI), tighter spacing
  throughout. Selected nodes get a subtle drop-shadow halo + small
  4×4 dark resize handles (no heavy blue rectangle outline).
- **Block-following animation**: 160 ms ease transition on node
  position/transform when not actively dragged; transition is force-
  disabled (`body.pyflw-copying` class) during the right-click clone
  so the duplicate sticks to the cursor instead of trailing.

### Tests

- 737 pytest pass (existing 712 + 19 sinks + 6 layout w/h).
- 79 vitest pass (existing tests + 19 dynamic-ports + 7 block-shapes
  + 3 block-glyph smoke).
- ruff, mypy strict, `npx tsc --noEmit`, `npm run build` all clean.
- `examples/spring_mass_damper.py` numerical output unchanged.

## [0.7.1] - 2026-05-07

ADR-0021 (Subsystem drilldown UI + mask parameters) Accepted. Phase 3
GUI completes: double-click any Subsystem to edit its inner diagram,
breadcrumb back-navigation, and Subsystems can declare `mask_params` to
expose tunable values that get substituted into inner block parameters
via `$Name` placeholders. Schema bumps 0.5 → 0.6 with a no-op
migration; mask-less Subsystems remain byte-identical to v0.7.0.

### Added
- `Subsystem(mask_params=..., mask_values=...)` declares scalar
  (`float` / `int` / `bool`) parameters that drive `$Name` placeholders
  in inner block params. `Subsystem.set_mask_value(name, value)` updates
  a value and triggers re-resolve at the next `_build`.
- `pyflw.subsystems._mask` placeholder helpers
  (`is_placeholder`, `extract_placeholder_name`, `substitute_placeholders`,
  `collect_placeholder_names`, `normalize_mask_params`).
- `Block.to_dict` honours a per-instance `_unresolved_params` snapshot,
  so JSON round-trip preserves the original `$Name` placeholders rather
  than the resolved concrete values.
- Block class registry: `is_container` and `mask_capable` fields exposed
  in `GET /api/v1/blocks` (auto-derived from `issubclass(cls, Subsystem)`).
  GUI uses `is_container` to gate double-click drill-down.
- Frontend: `editingPath` stack in the Zustand store with
  `drilldownInto` / `drillUp` / `setEditingPath` actions; `Breadcrumb`
  component (Top › sub_outer › sub_inner …); `pathResolver.ts` for
  immutable nested updates; `MaskValuesEditor` in `ParameterPanel`
  that renders type-aware inputs (number / int / bool) for declared
  mask parameters and writes through to `editingModel`.
- `tests/subsystems/test_mask.py` (24 tests): placeholder helpers,
  `normalize_mask_params`, mask defaults, explicit overrides, JSON
  round-trip, port-shape change rejection, schema 0.5 → 0.6 migration.
- `pyflw/web/frontend/tests/pathResolver.test.ts` (11 tests): nested
  resolve / immutable apply / findBlockAtPath edge cases.

### Changed
- `CURRENT_SCHEMA_VERSION` bumped from `"0.5"` to `"0.6"`.
  `_builtin_migrate_0_5_to_0_6` is a no-op `schema_version` rewrite
  (existing 0.1 → 0.6 chain continues to work).
- `Subsystem.to_dict` writes `mask_params` / `mask_values` into the
  `params` block (canonical order: `n_inputs`, `n_outputs`,
  `port_shapes_*`, `mask_params`, `mask_values`, `blocks`,
  `connections`, `layout`). Non-mask Subsystems omit both keys.
- `Subsystem._from_dict` substitutes placeholders against `mask_values`
  before instantiating each inner block, so `Gain(k="$Kp")` is never
  passed through to a constructor that would have called
  `float("$Kp")`. Affected blocks gain an `_unresolved_params` snapshot.
- `Subsystem._resolve_mask_placeholders` is invoked at the start of
  `_build`. It re-creates inner blocks against current `mask_values`,
  rewires downstream `input_sources` to the new instances (preventing
  dangling references that previously surfaced as `AlgebraicLoopError`),
  and rejects placeholder substitutions that would change `port_shapes_*`
  (per ADR-0017 static port-shape declaration).
- `DiagramCanvas` walks `editingPath` via `resolveBlocksAtPath` and now
  honours `onNodeDoubleClick` for `is_container` blocks.
- `appStore` edit helpers (`addBlockToEditing`, `removeBlock…`,
  `updateBlockPosition`, `addConnectionToEditing`, etc.) operate at the
  current `editingPath` rather than the root, so drill-down editing
  modifies the correct nested scope.
- `ParameterPanel` switches to the editing-model + path-aware
  `findBlockAtPath` and dispatches to `MaskValuesEditor` whenever the
  selected block declares mask parameters. Regular numeric edits commit
  on `onBlur` and rely on the existing 500 ms auto-save.

### Migration
- v0.7.0 (schema 0.5) files load unchanged via the new no-op migration;
  their Subsystems keep `mask_params is None` (mask-less).
- New mask-using JSON files round-trip placeholders verbatim. CLI /
  pytest with mask Subsystems must construct them via
  `Subsystem._from_dict` (or `Simulator.load`) — programmatic
  `Gain(k="$Kp")` is intentionally rejected by the existing constructor
  validations and is not part of the Phase 3 scope.

### Verified
- 712 pytest pass (existing 688 + 24 new mask tests). ruff and mypy
  strict clean. `examples/spring_mass_damper.py` numerical output
  unchanged.
- 50 Vitest pass (existing 39 + 11 pathResolver tests). `npx tsc
  --noEmit` clean. `npm run build` produces a 126 kB gzipped bundle.

### Phase 4 (deferred per ADR-0021 §11)
- Mask expressions (`$Kp + 0.1 * $Ki`) and a guarded evaluator.
- Variant subsystems where placeholders may change `port_shapes`.
- GUI editor for declaring mask parameters (currently declarative only).
- `array` / `matrix` / `function` mask param types.
- Cascading masks across nested Subsystems.
- Path-scoped viewport persistence (zoom / pan) and sharing of
  external `.flw.mask.json` libraries.

## [0.7.0] - 2026-05-06

ADR-0019 (GUI drag-and-drop + block palette + Block class registry REST)
Accepted. Phase 3 GUI core. The web app moves from read-only diagrams to
fully editable models: drag blocks from the palette, wire them up, and
the changes auto-save (500 ms debounce) through the existing PUT
/api/v1/models passthrough. Server runtime is unchanged.

### Added
- `GET /api/v1/blocks` — full Block class registry (35+ built-in blocks
  plus any prefix added via `register_block_module`). Each entry has
  `type_path`, `display_name`, `category`, `icon`, `color`,
  `docstring_summary`, `params_spec` (from `inspect.signature`),
  `default_n_inputs/outputs`, `port_shapes_in/out_default`, and `tags`
  (`sm_a` / `sm_b` / `stateful` / `source` / `sink`). Response includes
  `schema_version: "blocks.v1"` for independent versioning.
- `GET /api/v1/blocks/{type_path}` — single entry with the full
  docstring.
- `POST /api/v1/blocks/resolve-port-shapes` — given `{type_path,
  params}` returns the resolved `n_inputs / n_outputs / port_shapes_*`
  for parametric blocks (Mux/Demux/Sum/MimoTransferFunction etc.).
  HTTP 400 on `BlockSpecError`, 404 on unknown `type_path`.
- `pyflw.server.registry` — startup walker built on `pkgutil.walk_packages`
  + `inspect`. Centralized metadata table for the 33 built-in blocks plus
  class-attribute fallback (`_block_category`, `_block_display_name`,
  `_block_icon`, `_block_color`, `_default_factory_args`) for third-party
  extensions. `DeprecationWarning` (e.g. ZeroOrderHold) is suppressed
  during default factory probing.
- Frontend: `BlockPalette` component (search + collapsible categories +
  SM-B badge), drag-and-drop wiring in `DiagramCanvas` (palette → canvas,
  node move, edge create/delete with port-shape validation, Backspace /
  Delete to remove), `useAutoSave` hook (debounce 500 ms + Ctrl+S +
  beforeunload guard), `Create New Model` form in `ModelList`, dirty
  indicator (`*`) in the header, sidebar tabs (Models / Palette).
- Frontend lib helpers: `portShapeValidate.ts` (strict shape equality +
  registry indexing), `idGenerator.ts` (`{TypeName}_{counter}` ID with
  collision avoidance, default param fallback by type label).
- `tests/server/test_blocks_registry.py` (20 tests) covers
  `/api/v1/blocks` (canonical sort, 33+ entries, category coverage,
  no `unknown` tag), `GET /{type_path}` (404, full docstring),
  `resolve-port-shapes` (Mux/Demux/Sum dynamic shapes, HTTP 400/404).
- Frontend Vitest suites: `portShapeValidate.test.ts` (12 tests),
  `idGenerator.test.ts` (8 tests).

### Changed
- `Simulator` runtime is **unchanged**. The new endpoints live in the
  server layer; CLI / pytest behaviour is bit-for-bit compatible with
  v0.6.2.
- `App.tsx` wraps the layout in `<ReactFlowProvider>` so the palette and
  canvas can share the same React Flow instance for `screenToFlowPosition`.
- `DiagramCanvas` no longer hardcodes `nodesDraggable={false}`; it now
  edits `editingModel` in the Zustand store and relies on `useAutoSave`
  to persist changes.
- Header version label updated to `v0.7.0-dev0` and now shows the
  current model id with a `*` suffix when there are unsaved changes.

### Verified
- 688 pytest pass (existing 668 + 20 new registry tests). ruff and
  mypy strict clean. `examples/spring_mass_damper.py` numerical output
  unchanged.
- 38 Vitest pass (existing 18 + 12 portShapeValidate + 8 idGenerator).
  `npx tsc --noEmit` clean. `npm run build` produces a 124 kB gzipped
  bundle (within the ADR-0012 §Risks #6 budget).

### Phase 4 (deferred)
- Undo / redo, multi-select, copy-paste, keyboard shortcuts beyond
  Ctrl+S (ADR-0019 §(10) OP-A).
- Orthogonal edge routing.
- Subsystem drill-down + mask parameters → ADR-0021.
- Hot-reload of `register_block_module` extensions (admin endpoint).
- Playwright E2E coverage beyond smoke (ADR-0019 §9.3).

## [0.6.2] - 2026-05-06

ADR-0020 (JSON schema layout persistence) Accepted. Schema bump
0.4 → 0.5. Foundation for ADR-0019 drag-and-drop GUI. Pure SM-A
models saved without `layout=` differ from v0.6.1 only in
`schema_version` (`"0.5"`) and `metadata.tool` (`"pyflw 0.6.2"`);
all other bytes are unchanged.

### Added
- Top-level `layout` field in `.flw.json`: optional `{block_id:
  {x: float, y: float}}` recording GUI node positions. Subsystem
  internal layout lives in `params.layout` (recursive). Both are
  optional; missing entries fall back to React Flow grid auto-layout.
- `Simulator.save(path, *, layout=None)` accepts an optional layout
  dict. When `None` or empty, the `layout` key is omitted from the
  output JSON (CLI / pytest models stay byte-identical).
- `Simulator.last_loaded_layout` attribute (read-only) holds the
  layout extracted from the most recent `Simulator.load()` call.
  `None` for layout-less files. Runtime behaviour unchanged.
- `Subsystem.__init__(layout=...)` and the corresponding
  `Subsystem.layout` attribute carry inner-block positions through
  save/load round-trips.
- `pyflw.core.persistence.normalize_layout(value)` validates and
  normalizes any `LayoutDict`-shaped input (None, ints, etc.) into
  the canonical `dict[str, dict[str, float]]` form.
- Frontend `nodesToLayout(nodes)` helper builds a `LayoutDict` from
  React Flow nodes for save-time persistence.
- `tests/core/test_layout_persistence.py` (26 tests) covers schema
  bump, migration chain (0.1→0.5), no-op save, round-trip, partial
  layouts, stale-id pruning with warning, Subsystem inner layout,
  and `normalize_layout` validation.
- Frontend `nodesToLayout` and grid-fallback Vitest cases.

### Changed
- `CURRENT_SCHEMA_VERSION` bumped from `"0.4"` to `"0.5"`.
- `_builtin_migrate_0_4_to_0_5` registered as a no-op `schema_version`
  bump (`layout` is optional). Existing 0.1〜0.4 files load unchanged.
- `diagramConverter.modelToDiagram(model)` consults `model.layout`
  before falling back to grid auto-layout. Backward compatible:
  models without `layout` look identical to v0.6.1.

### Migration
- Files saved by v0.6.1 (schema 0.4) load unchanged via the new no-op
  migration; their `layout` is `None`.
- New files saved without `layout=...` argument are byte-identical to
  v0.6.1 except for `schema_version: "0.5"`.
- Server (FastAPI) is raw passthrough, so `layout` round-trips through
  `PUT /api/v1/models/{id}` without server-side changes.

### Verified
- 668 tests pass (existing 641 + 26 layout + 1 server round-trip).
- Frontend Vitest: 18 tests pass (10 existing + 8 new layout cases).
- `ruff check pyflw tests` and `mypy pyflw` clean.
- `npx tsc --noEmit` clean for frontend.
- `examples/spring_mass_damper.py` numerical output unchanged.

## [0.6.1] - 2026-05-06

Phase 3 #4 (Mux / Demux + SM-B run path integration). ADR-0018 Accepted.

### Added
- `pyflw.blocks.Mux(n)`: aggregates `n` scalar inputs into a single
  rank-1 vector of shape `(n,)`. `direct_feedthrough=True`, no state.
  `port_shapes_in = ((), ..., ())`, `port_shapes_out = ((n,),)`.
- `pyflw.blocks.Demux(n)`: splits a rank-1 vector input of shape
  `(n,)` into `n` scalar outputs. Inverse of `Mux`.
  `port_shapes_in = ((n,),)`, `port_shapes_out = ((), ..., ())`.
- `Inport` / `Outport` accept a `port_shape` keyword argument
  (default `()`) for SM-B subsystem boundaries. The internal
  `_external_value` is initialized as a float for SM-A or as an
  `np.ndarray` for SM-B. JSON serialization includes `port_shape` only
  when non-default.
- `Subsystem._build` now reconciles outer `port_shapes_in[i]` /
  `port_shapes_out[j]` with the inner `Inport(port_idx=i).port_shape` /
  `Outport(port_idx=j).port_shape`. Mismatches raise `BlockSpecError`.
- `Subsystem.to_dict` / `_from_dict` round-trip the SM-B
  `port_shapes_in` / `port_shapes_out` (when non-default), so an SM-B
  Subsystem can be saved and reloaded without losing its outer port
  declarations. Pure SM-A Subsystems remain byte-identical in JSON.
- `Simulator._check_subsystem_sm_b_unsupported`: when SM-B mode is
  active and any `Subsystem` declares a non-scalar port, `run()` raises
  `BlockSpecError` (Phase 4 will add `_step_inner_v`). This avoids the
  silent-truncation failure mode where SM-B input ndarrays would be
  coerced via `float(...)` inside the SM-A `_step_inner` path.
- `Simulator._step_vector` now validates that an `output_v` override
  returns exactly `n_outputs` items, catching mis-implemented
  vector-aware blocks at the source instead of as obscure downstream
  shape errors.
- `tests/blocks/test_mux_demux.py` / `test_mux_demux_edge_cases.py`
  (56 tests), `tests/core/test_sm_b_run.py` /
  `test_sm_b_run_edge_cases.py` (29 tests), and
  `tests/subsystems/test_subsystem_sm_b.py` (25 tests including SM-B
  Subsystem JSON round-trip and Phase-4 rejection regressions) cover
  the new SM-B paths end-to-end.

### Changed
- `Simulator.run()` dispatches to `_run_sm_a_loop()` (existing hot path,
  bit-for-bit compatible with v0.6.0) or to the new `_run_sm_b_loop()`
  for models that contain any SM-B port. The SM-B loop builds outputs
  via `_step_vector(...)` and integrates continuous states using a
  `f_continuous_vector` adapter that bridges SM-A `derivative()` blocks
  (e.g. `Integrator`) by collapsing the SM-B input tuple to a 1D
  ndarray. Pure SM-A models never enter the SM-B path.
- `Block.to_dict()` honours a new `_serialize_port_shapes` class flag.
  Mux / Demux / Inport / Outport set it to `False` so their
  `port_shapes_*` are derived from `n` / `port_shape` at load time and
  are never written to JSON twice.
- The framework-internal `Inport` / `Outport` blocks set
  `_skip_dual_api_check = True` so the ADR-0017 §(8) U3 dual-API guard
  does not flag their intentional `output` + `output_v` co-existence.
- `Scope` is asserted to be SM-A only at build time when SM-B mode is
  active (`Simulator._check_scope_inputs_are_scalar`). Connecting a
  vector signal directly to a `Scope` raises `BlockSpecError` with a
  hint to insert a `Demux` first.

### Migration
- Pure SM-A models: no action required, JSON is byte-identical.
- ADR-0017 schema 0.4: unchanged.
- The placeholder `BlockSpecError("SM-B vector ports detected, but the
  SM-B simulation runtime is not yet wired up")` from v0.6.0 is gone;
  SM-B models now run directly. Tests that asserted that error
  (`TestSmBRunNotImplemented`, `TestSmBRunErrorMessage`) have been
  renamed to `TestSmBRunEnabled` and verify successful completion.

### Verified
- 641 tests pass (existing 541 + 100 new SM-B tests including
  edge-case suites and code-reviewer regression coverage).
- `ruff check pyflw tests` and `mypy pyflw` clean.
- `examples/spring_mass_damper.py` numerical output unchanged
  (`Final x=0.2505, x_dot=0.0031`).

## [0.6.0] - 2026-05-06

Phase 3 #3 (signal model SM-B). ADR-0017 Accepted.

### Changed (BREAKING)
- `Block.__init__` accepts two new optional keyword arguments,
  `port_shapes_in` and `port_shapes_out`. They default to `None` (= all
  ports are SM-A scalars represented as rank-0 shape `()`), so all 33
  bundled blocks are unaffected.
- `Simulator` runs a build-time port-shape consistency check inside
  `_execution_order()`. When a `connect()` joins ports whose declared
  shapes disagree, a `BlockSpecError` is raised with a hint to use
  Mux/Demux (Phase 3 #4) for scalar/vector adaptation.
- JSON schema bumped 0.3 -> 0.4. The `port_shapes_in` / `port_shapes_out`
  fields are reserved as **optional**; for SM-A models the on-disk JSON
  is unchanged. Migration is handled automatically via the existing
  `migrate_to_current` chain (`schema_version` string update only).

### Added
- `Block.output_v(t, x, u)` SM-B vector-port API. The default
  implementation wraps `Block.output(...)` so SM-A blocks remain
  unchanged. SM-B-aware blocks (e.g. forthcoming Mux / Demux) override
  `output_v`.
- `Simulator._step_vector(...)` scaffolding that walks the topological
  order using tuple-of-ndarray inputs/outputs. Wired up at run-time in
  Phase 3 #4 once the first vector-aware blocks ship.
- `Simulator._is_sm_a_mode()` helper used by `run()` to fast-path
  scalar-only models. SM-B-only models currently raise a clear
  `BlockSpecError` ("SM-B vector ports detected, but the SM-B simulation
  runtime is not yet wired up"); this is intentional Phase 3 #3
  scaffolding and will be lifted by Phase 3 #4.
- `Subsystem.__init__` accepts `port_shapes_in` / `port_shapes_out` so
  composite blocks can declare vector boundaries; internal `Inport` /
  `Outport` reconciliation is part of Phase 3 #4.
- `tests/core/test_port_shapes.py`: 21 new tests covering port-shape
  normalization, SM-A compatibility, build-time mismatch errors,
  `output_v` wrapper behaviour, the SM-B run-time placeholder, and
  schema 0.3 -> 0.4 migration (including chained 0.2 -> 0.3 -> 0.4).
- `tests/core/test_port_shapes_edge_cases.py`: 96 additional edge-case
  tests covering boundary conditions, all 33 bundled blocks, Subsystem
  round-trip, rank-0 conversion fidelity, and SM-A/SM-B mode detection.

### Deferred to Phase 3 #4
- SM-B run-time integration (`run()` dispatch, scope record / Integrator
  derivative bridging through the vector pipeline).
- Concrete `Mux` / `Demux` blocks.
- Subsystem internal `Inport` / `Outport` port-shape reconciliation.

## [0.5.0] - 2026-05-06

Phase 3 opens. ADR-0016 (Phase 3 architecture overview) is now Accepted; it
sets the priorities, versioning plan (v0.5.0 -> v0.9.0), and the items
deferred to Phase 4 (RateTransition, triggered subsystems, SPEC-0001 #16-#21).

### Added
- `pyflw.blocks.MimoTransferFunction`: continuous-time MIMO LTI transfer
  function with shared denominator (ADR-0010 §(2), ADR-0016 Phase 3 #1).
  Implementation builds the controllable canonical form manually via
  `pyflw.blocks._lti_utils.build_companion_form_siso` to side-step the
  `scipy.signal.tf2ss` zero-numerator bug; the realization is the parallel
  composition of one SISO companion-form block per `(i, j)` entry, joined
  through a block-diagonal `A` (state size `p*q*n`). Phase 3 supports the
  **shared-denominator** form only; per-entry independent denominators are
  deferred to Phase 4+.

### Deprecated
- `pyflw.blocks.ZeroOrderHold` now emits a `DeprecationWarning` on
  construction (ADR-0014 §(4), ADR-0016 Phase 3 #2). It is functionally
  identical to `UnitDelay` since v0.3.0 (ADR-0014) and is scheduled for
  removal in Phase 4. Migrate to:
  - `UnitDelay` for 1-sample delayed sample-and-hold, or
  - `ZeroOrderHoldDirect` for Simulink-compatible immediate reflection
    (`y(t_k) = u(t_k)`).

### Documentation
- `.claude/docs/adr/0016-phase3-architecture-overview.md` (Accepted).

## [0.4.0] - 2026-05-06

### Changed (BREAKING)
- **Multi-rate Simulink semantics fix (ADR-0015)**: All discrete blocks now match
  Simulink's `y(t in [n*T, (n+1)*T)) = u((n-1)*T)` semantics in the multi-rate
  case (`sample_time > dt_base`). The `1 dt_base` off-by-one limitation noted in
  v0.3.0's "Known limitations" is resolved.
  - Implementation: `Simulator.run()` fires updates at sample boundary START
    (`k % step_ratio == 0`) before `[A]` output, using a 2-pass approach.
  - All discrete blocks adopt **2-state augmentation**:
    - `UnitDelay` / `ZeroOrderHold`: `n_states` 1 → 2 (state[0]=output_curr,
      state[1]=output_next).
    - `DiscreteIntegrator`: `n_states` 1 → 2.
    - `DiscreteStateSpace` / `DiscreteTransferFunction`: `n_states` n → 2n.
  - `ZeroOrderHoldDirect` is unchanged (df=True direct reflection still works).
- **JSON schema bumped 0.2 → 0.3**: external `x0` representation in JSON is
  preserved (still scalar / shape-(n,)); internal expansion to 2-state is
  handled by Block `__init__`. Migration is automatic via the existing
  `migrate_to_current` chain.
- Single-rate (`sample_time = dt_base`) numerical results are unchanged for
  open-loop usage. Single-rate **feedback** loops through `UnitDelay` /
  `ZeroOrderHold` may produce different output sequences (period extends from
  2 to 4) due to the 2-state register semantics — this is consistent with
  Simulink's 2-state internal model and was implicit in v0.3.0's 1-state
  approximation.

### Added
- `tests/test_multirate_simulink.py`: 10 regression tests pinning the
  Simulink-compatible multi-rate semantics for all five discrete block types.
- Playwright E2E smoke tests for the Web GUI (`pyflw/web/frontend/tests/e2e/`).
  Covers root render, model list, model selection, and Run button +
  WebSocket completion. Run locally with
  `npm --prefix pyflw/web/frontend run e2e`.
- CI: `.github/workflows/ci-frontend.yml` gains an `e2e` job that installs
  pyflw with `[gui]` extras, caches Playwright browsers, and runs the
  smoke suite on every frontend PR.
- `ParameterPanel` component for inline editing of numeric block parameters
  (ADR-0012 §(3); §(10) "Phase 3 deferred" for this item is withdrawn).
  Click a node in the diagram to populate the right-hand panel; numeric
  fields become editable and the Save button persists via
  `PUT /api/v1/models/{id}`. Non-numeric params (lists, objects, strings)
  are surfaced as a read-only collapsible JSON view.
- `pyflw/web/frontend/tests/paramEdit.test.ts` (10 unit tests) and
  `tests/e2e/parameter-panel.spec.ts` (2 E2E tests) covering the new
  ParameterPanel behavior.

### Changed
- CI workflows are split: `ci.yml` (Python lint/type/test/docs) and
  `ci-frontend.yml` (Vite/Vitest/Playwright). Each uses `paths` filters
  so that pure-Python PRs no longer pay the npm install/build cost and
  vice versa.
- Web frontend layout extended to a 3-column grid (Models | Diagram |
  Parameters) to host the new ParameterPanel.

### Fixed
- `vitest.config.ts` now excludes `tests/e2e/**` so Vitest no longer
  mis-collects Playwright specs (which uses `@playwright/test`'s own
  `test.describe`).

### Documentation
- `.claude/docs/adr/0015-multirate-unitdelay-2-state-refactor.md` (Accepted).
- ADR-0014 marked as partially superseded by ADR-0015 (multi-rate parts only;
  single-rate Decision and `(t_k, u(t_k))` semantics retained).

## [0.3.0] - 2026-05-06

### Changed (BREAKING)
- **Simulator loop semantics fix (ADR-0014)**: `update(t, x, u)` is now invoked
  with the current sample time `t_k` and the input sampled at `t_k`
  (`u(t_k)`), not the next sample time `t_new = (k+1)*dt_base`. This brings
  numerical results of all discrete blocks in line with standard discrete-time
  LTI semantics (`x[k+1] = f(x[k], u[k])`) and Simulink convention. As a
  consequence, **numerical results of `UnitDelay`, `ZeroOrderHold`,
  `DiscreteIntegrator`, `DiscreteStateSpace`, `DiscreteTransferFunction`
  change** when `sample_time = dt_base` (single-rate). Specifically:
  - `UnitDelay` now produces a genuine 1-sample delay `y[k+1] = u[k]` (was
    effectively 0-sample delay before).
  - `ZeroOrderHold` becomes behaviorally identical to `UnitDelay`
    (1-sample-delayed sample-and-hold). For Simulink-compatible immediate
    reflection (`y(t_k) = u(t_k)`), use the new `ZeroOrderHoldDirect` block.
  - `DiscreteIntegrator` now matches the standard forward Euler
    `x[k+1] = x[k] + T*g*u[k]` (the previous version had a 1-step index shift).
  - `DiscreteStateSpace` / `DiscreteTransferFunction` now match the standard
    discrete-time LTI form `x[k+1] = A x[k] + B u[k]`.
- Models created with v0.2.0 will produce different numerical outputs at
  sample boundaries when discrete blocks are involved. Continuous-only models
  (e.g. `examples/spring_mass_damper.py`) are unaffected.
- ADR-0005 §(4) is partially superseded by ADR-0014 §(1). ADR-0002 §(4) is
  updated to reflect the new loop. ADR-0010 §(5)(6) erratum: the prior claim
  that `ZeroOrderHold` was equivalent to `UnitDelay` was incorrect; with
  ADR-0014 it now becomes equivalent. The Phase 3 deferral of
  `ZeroOrderHoldDirect` is withdrawn.

### Added
- `pyflw.blocks.ZeroOrderHoldDirect`: true Simulink Zero-Order Hold
  (`direct_feedthrough=True`, `y(t_k) = u(t_k)` immediate reflection,
  hold between sample times). See ADR-0014 §(3).
- `tests/test_simulink_semantics.py`: regression tests pinning the
  Simulink-compatible semantics of all discrete blocks (`UnitDelay`,
  `ZeroOrderHold`, `ZeroOrderHoldDirect`, `DiscreteIntegrator`,
  `DiscreteStateSpace`, `DiscreteTransferFunction`).
- `.claude/docs/adr/0014-simulator-update-timing-fix.md` (Accepted, 2026-05-06).

### Deprecation notice
- `pyflw.blocks.ZeroOrderHold` is now behaviorally identical to `UnitDelay`
  and is scheduled for `DeprecationWarning` in Phase 3 and removal in Phase 4.
  Migrate to `UnitDelay` (for delayed sample-and-hold) or `ZeroOrderHoldDirect`
  (for immediate-reflection ZOH).

### Known limitations
- For multi-rate discrete blocks (`sample_time > dt_base`), the new loop
  samples `u` at `t = (n*step_ratio - 1) * dt_base` instead of the
  conceptual sample boundary `t = n*sample_time`, leading to a one-`dt_base`
  off-by-one shift compared to Simulink. A complete fix requires a 2-state
  refactor of `UnitDelay` / `ZeroOrderHold` and is deferred to a future ADR.
  For now, prefer `sample_time = dt_base` (single-rate) for full Simulink
  compatibility.

## [0.2.0] - 2026-05-06

### Added
- JSON model persistence: `Simulator.save(path)` / `Simulator.load(path)` with
  schema_version 0.2 (ADR-0008, ADR-0009).
- Atomic Subsystem with internal mini-scheduler, including
  `pyflw.subsystems.{Inport, Outport, Subsystem}` (ADR-0009).
- 0.1 -> 0.2 schema migration registered as the first built-in migration.
- FastAPI Web GUI backend at `/api/v1/` with REST CRUD, simulation control, and
  WebSocket scope streaming (ADR-0011). New optional dependency group
  `pyflw[gui]`.
- React + TypeScript frontend skeleton under `pyflw/web/frontend/` (Vite,
  Zustand, TanStack Query, React Flow, Tailwind, ADR-0012). Read-only diagram
  view + Run/Stop + live scope canvas.
- `pyflw-server` console script entry point that launches FastAPI via uvicorn
  with sensible localhost defaults (ADR-0013).
- `pyflw.SimulationStillRunningError` and `pyflw.core.identifiers.validate_model_id`.
- `Simulator.on_step_callback` and `Simulator.request_stop()` /
  `Simulator.is_stopped` for cooperative cancellation from the server runtime.
- Release workflow (`.github/workflows/release.yml`) that builds the frontend,
  stages it under `pyflw/server/static/`, and publishes wheel+sdist to GitHub
  Releases on `v*` tag push.
- LICENSE (MIT, declared in `pyproject.toml` per PEP 639).
- `tests/test_version_consistency.py` enforcing `pyflw.__version__` ==
  `pyproject.toml [project].version`.

### Changed
- Block class registry uses an allowlist (default `pyflw.*`); third-party
  modules opt in via `register_block_module(prefix)` to mitigate hostile
  `.flw.json` files (ADR-0008).
- ADR-0010 formalizes signal model SM-A (each port carries one scalar);
  `Mux` / `Demux` and a `direct_feedthrough=True` ZeroOrderHold variant are
  deferred to Phase 3.
- ADR-0006 / 0007 / 0009 cross-reference cleanup; SPEC-0001 §未決事項 entries
  resolved by ADR-0005 / 0009 / 0010 / 0012.
- `pyproject.toml` build requirement raised to `setuptools>=71` for full PEP 639
  license expression support.

### Deferred to Phase 3
- True `ZeroOrderHoldDirect` (`direct_feedthrough=True`) — needs the ADR-0005
  step loop to be revisited.
- `MimoTransferFunction` (common-denominator and per-element variants).
- `Mux` / `Demux` blocks together with the SM-B vector-port signal model.
- Frontend drag-and-drop editing, block palette, parameter inline editor.
- Subsystem drill-down UI in the diagram canvas.
- PyPI publish automation in the release workflow (manual `twine upload` for
  now).

## [0.1.0] - 2026-05-05

### Added
- Phase 1 core engine: `Block` base class, `Simulator` (`scipy.solve_ivp`
  hybrid loop), 21 standard blocks across Sources / Sinks / Continuous /
  Discrete / Math / Logic / Routing including LTI (StateSpace,
  TransferFunction, Derivative, DiscreteStateSpace, DiscreteTransferFunction).
- `@block` decorator DSL with both function (Option A) and class (Option C)
  forms (ADR-0003).
- Multirate scheduler with integer-counter step ratios, inheritance for
  `sample_time = -1.0`, and warnings for non-integer ratios (ADR-0002, ADR-0005).
- Block ID convention `{type_name}_{counter}` with auto-numbering and
  `Simulator.rename` (ADR-0004).
- GitHub Actions CI matrix (ruff, mypy --strict, pytest 3.10/3.11/3.12/3.13,
  Sphinx warnings-as-errors).
- Sphinx documentation initial release: quickstart, blocks reference,
  decorator guide, API reference.

[Unreleased]: https://github.com/aramoto99/pyflw/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/aramoto99/pyflw/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/aramoto99/pyflw/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/aramoto99/pyflw/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/aramoto99/pyflw/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aramoto99/pyflw/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aramoto99/pyflw/releases/tag/v0.1.0
