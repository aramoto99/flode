// ADR-0044 follow-up: ScopeSettingsDialog の isXY 分岐 (Display タブ) を検証。
// i18n 文言に依存しないよう、構造 (option[value] / checkbox 数) で差を assert する。

import "../src/i18n"; // useTranslation を動かすため初期化

import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ScopeSettingsDialog } from "../src/components/ScopeSettingsDialog";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function setModel(): void {
  useAppStore.setState({
    editingModel: {
      schema_version: "1.0",
      blocks: [],
      connections: [],
      config: { t_end: 1, dt: 0.01, solver: "RK45" },
    } as unknown as FlwModel,
    scopes: {},
  });
}

beforeEach(() => {
  setModel();
});

afterEach(() => {
  cleanup();
});

describe("ScopeSettingsDialog isXY branch (Display tab)", () => {
  it("Scope (isXY=false) shows log option, legend select, 2 grid checkboxes", () => {
    const { container } = render(
      <ScopeSettingsDialog scopeId="s" onClose={() => {}} />,
    );
    // Y スケールの log 選択肢
    expect(container.querySelector('option[value="log"]')).not.toBeNull();
    // 凡例 select (= option value="right" は凡例固有)
    expect(container.querySelector('option[value="right"]')).not.toBeNull();
    // major + minor grid の 2 チェックボックス
    expect(
      container.querySelectorAll('input[type="checkbox"]').length,
    ).toBe(2);
  });

  it("XYGraph (isXY=true) hides log option, legend select, minor grid", () => {
    const { container } = render(
      <ScopeSettingsDialog scopeId="xy" isXY onClose={() => {}} />,
    );
    expect(container.querySelector('option[value="log"]')).toBeNull();
    expect(container.querySelector('option[value="right"]')).toBeNull();
    // major grid の 1 チェックボックスのみ (minor grid は隠す)
    expect(
      container.querySelectorAll('input[type="checkbox"]').length,
    ).toBe(1);
  });
});
