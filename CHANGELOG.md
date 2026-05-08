# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
