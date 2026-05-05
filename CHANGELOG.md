# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 2 in progress, will be released as 0.2.0)
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

### Changed
- Block class registry uses an allowlist (default `pyflw.*`); third-party
  modules opt in via `register_block_module(prefix)` to mitigate hostile
  `.flw.json` files (ADR-0008).
- ADR-0010 formalizes signal model SM-A (each port carries one scalar);
  `Mux` / `Demux` and a `direct_feedthrough=True` ZeroOrderHold variant are
  deferred to Phase 3.
- ADR-0006 / 0007 / 0009 cross-reference cleanup; SPEC-0001 §未決事項 entries
  resolved by ADR-0005 / 0009 / 0010 / 0012.

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

[Unreleased]: https://github.com/aramoto99/pyflw/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aramoto99/pyflw/releases/tag/v0.1.0
