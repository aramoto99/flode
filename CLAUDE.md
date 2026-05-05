# エンジニアリング原則

## 応答言語

- 常に日本語で回答（コード・ファイルパス・技術用語は英語のまま）

## プロジェクト概要

**pyflw**: ブロック線図ベースの動的システムシミュレータ (Simulink-inspired、商標回避のため独自命名)。

- **言語/環境**: Python 3.10+ / Windows (PowerShell + WSL Bash 併用)
- **主要依存**: numpy, scipy (`solve_ivp` で連続系ODE積分、既定 RK45), matplotlib (Scope のプロット)
- **パッケージ構成**:
  - `pyflw/core/` — `Block` 基底クラス、`Simulator` (トポロジカルソートで実行順を決定 + 代数ループ検出)
  - `pyflw/blocks/` — `sources` (Constant/Step/Sine) / `mathops` (Gain/Sum/Product) / `continuous` (Integrator) / `sinks` (Scope)
  - `examples/` — 動作確認用 (`spring_mass_damper.py` など)
- **設計の要点**:
  - 各ブロックは `output(t, x, u)` と (連続系のみ) `derivative(t, x, u)` を実装
  - `direct_feedthrough=False` のブロック (Integrator 等) が代数ループを切る
  - Simulator は全ブロックの状態を1本のベクトルに連結して `solve_ivp` に渡す
  - 出力計算は2パス: ① 直達ブロックをトポ順に計算 → ② 非直達ブロックの入力を組み立て (微分計算用)
- **GUI**: 現状は CLI/スクリプトのみ。将来的にデスクトップ (PySide6 + NodeGraphQt) or Web (FastAPI + React Flow) を検討

### 命名上の制約

- `simulink` という語をモジュール / パッケージ / クラス / ファイル / ディレクトリ名に使わない (商標)。プロジェクトの説明文で「Simulink-inspired」と書くのは可

---

## 調査・デバッグの鉄則

- **原因を特定する前にコードを修正しない**。事実（ログ、プロセス状態、ネットワーク疎通）を先に確認する
- 差分を見せて判断を仰げと言われたら、勝手にファイルを編集しない
- ユーザーのオペレーションミスを疑うのは最後の手段。インフラ・環境の一時的問題を先に考慮する
- 恒久的な問題と一時的な問題の両方を考慮する
- **「現在の○○は××です」と状態を断定する前に、事実を再取得する**。
  セッション開始時の `git status` / `git log` 出力、既読のファイル内容、memory を
  「現在」として扱わない。`git fetch --tags` / ファイル再 Read / プロセス状態確認で
  更新してから語る。特に**別 repo / サブモジュール / 外部サービスの状態**は
  明示的に fetch しないと古い情報で判断することになる

## 作業フロー

- **複数ファイルにまたがる変更・不慣れな領域・大きな設計判断**は Plan Mode で計画を先に提示する
- 単純な修正（typo、ログ追加、リネーム、1ファイル内の局所修正）は直接実施してよい
- 実装後は必ず**自己検証する手段を用意する**: テスト実行、型チェック、ビルド、スクリーンショット比較
- 同じ問題で2回修正しても直らなければ `/clear` で context をリセットし、プロンプトを書き直す
- 調査で広範囲のファイルを読む必要がある場合は subagent に委譲して main context を汚さない

## 判断と escalation

- **確信度を必ず表明する**（✅高 / ⚠️中 / ❓低）
- **破壊的・不可逆な操作**（本番DB操作、force push、一括削除、認可変更）は実行前に diff と影響範囲を提示して承認を求める
- **仕様に曖昧さ**があれば `AskUserQuestion` で確認する。勝手に解釈を決めない
- 詳細は `.claude/docs/escalation.md` を参照

---

## ツール使用ポリシー

### Bash tool の description 記述ルール

コマンド単体を読まなくてもユーザーが承認判断できるよう、description には
**「何をするか」+「なぜ必要か」** の 2 要素を含める。

- ❌ 「final diff summary」（何・なぜが不明）
- ✅ 「仮想 PR ドキュメント作成のため両 repo の最終 diff を確認」
- ✅ 「判定バグ修正の回帰テストとして pytest を実行」

短くてよいが、承認判断に必要な情報が揃うこと。

---

## Andon（`.claude/` の KAIZEN トリガー）

日常の会話で以下を検知したら、**その瞬間に** `.claude/pending_updates.md` に候補を追記する。
レビュー・適用・月次アーカイブは `/reflect` skill が担当し、必ずユーザー承認を経て反映する。

### 検知トリガー

- **ユーザー訂正**: "no" / "don't" / "stop" / "違う" / "そうじゃない" / "やめて"
- **"今後は" 発言**: "次から〜して" / "毎回〜するな" / "これからは〜"
- **明示的なメモ指示**: "覚えておいて" / "記録して"
- **反復**: セッション跨ぎで同じ注意 / 同じ失敗を 2 回以上

### 追記内容

`.claude/pending_updates.md` 冒頭のスキーマに従い、最低限
`trigger` / `target` / `context` / `proposed-change` / `criteria-match` を埋める。
候補段階なので精度は問わない（`/reflect` で再評価）。

### 自律の境界

- ✅ 自律: `pending_updates.md` 追記 / MEMORY 追加
- ❌ 承認必須: skill / agent / CLAUDE.md / settings / hook の書き換え

採用基準と除外フィルタは `.claude/docs/evolution-criteria.md` を参照。

---

## 標準ワークフロー

作業種別ごとに以下のチェーンで進める。**前工程は後工程を明示的に呼ぶ**（chain を自動継続させる責任を持つ）。

### (A) 新機能開発 / 機能変更（仕様変更を伴う）

```
[要なら] spec-interviewer → [要なら] architect → implement-feature
                         → [要なら] test-writer → [要なら] security-reviewer
                         → code-reviewer → create-pr
```

**「要なら」の判断基準** — 以下の「呼ぶ条件」に**該当する時だけ**呼ぶ（該当しなければ skip が正解）:

- **spec-interviewer**: 新機能の追加 / 既存仕様の追加・削除（フィールド・validation・UI 挙動の変更）/ 非機能要件に関わる定数変更（タイムアウト・リトライ・並行数等）。**skip 可**: 純粋な文言・ラベル変更、既存仕様を変えないログ追加、SPEC に書き足す情報がない局所修正
- **architect**: 暗号・CSPRNG・DB スキーマ・公開 API・認証・非機能要件・複数の実装戦略
- **test-writer**: 重要機能・エッジケースの網羅が必要（`implement-feature` が書く最小限テストで不十分な時）
- **security-reviewer**: 認証・認可・入力検証・秘密情報・暗号を扱うコード

### (B) バグ修正（仕様通りに動いていない問題）

```
[要なら] debugger → bug-fix → [要なら] security-reviewer
                 → code-reviewer → create-pr
```

- **debugger を呼ぶ条件**: 原因が不明、再現困難、断続的障害、本番障害（単純なエラー解消なら不要）
- `bug-fix` skill は **再現テスト → 最小修正 → 回帰テスト** を強制。ついでリファクタ禁止
- SPEC 更新は原則不要（仕様通りに動かすための修正のため）

### 共通ルール

- **呼ぶ条件に該当しなければ skip が正解**（「念のため呼ぶ」は過剰）。呼ぶ / skip の判断理由を 1 行添える
- **`code-reviewer` と `create-pr` は常に必須**（品質ゲート、skip 不可）
- 粒度判断は `.claude/docs/specs/README.md` の「既存機能を変更する時の粒度判断」を参照
- **完了報告 ≠ テスト通過**。`code-reviewer` agent のチェックまで含めて完了。
  skill を正式に invoke せず会話流れで Edit/Write に進まない

## Agent と Skill の区別

誤った invocation（`Skill(spec-interviewer)` 等）を避けるため明記:

- **Agents** (`.claude/agents/*.md` / Agentツールで dispatch):
  `spec-interviewer` / `architect` / `code-reviewer` / `security-reviewer` / `debugger` / `test-writer` / `doc-writer` / `dependency-updater`
- **Skills** (`.claude/skills/*/SKILL.md` / Skill invocation or slash command):
  `implement-feature` / `bug-fix` / `create-pr` / `simplify` / `reflect`

---

## 設計原則

- 単一責任: 1関数・1クラスは1責務
- テストは本体と同じ階層構造・モジュール名（例: `src/utils/parser.py` → `tests/utils/test_parser.py`）
- 1箇所からしか呼ばれない共通化や、使われていない抽象化は避ける
- マジックナンバー・設定値は定数 or 環境変数・設定ファイルに切り出す

---

## プロジェクト固有のコーディングルール

Claudeのデフォルト挙動と異なる、重要な規約のみ記載する。
（PEP8/ESLint等の言語標準はリンター・pre-commit で担保する前提）

### Python
- docstring は **Google Style**（Read the Docs 前提）
- 素の `Exception` を raise / catch しない。ドメイン固有のカスタム例外を `exceptions.py` に定義
- `print` デバッグ禁止、標準 `logging` モジュールを使う（ログに文脈情報を含める）
- テストは pytest、fixtureとparametrizeを活用、mockは `pytest-mock` の `mocker` fixture

### TypeScript
- strictモード、`any` 型禁止
- JSDoc で関数・コンポーネントのドキュメント記述

<!-- より詳細な規約やファイル配置ルールは `docs/coding-style.md` / `docs/file-layout.md` に分離し、
     必要に応じて Claude に参照させる（進行中タスクに関係しない時は context を消費させない） -->

---

## 用語集

プロジェクト固有の多義語は `.claude/docs/glossary.md` に定義する。
Claude は多義語を使う前にこのファイルを参照し、定義と異なる意味で使う場合は「私はこの意味で使います」と明示する。
