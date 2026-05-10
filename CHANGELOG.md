# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
