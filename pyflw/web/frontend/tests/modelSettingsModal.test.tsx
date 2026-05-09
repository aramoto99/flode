// v0.16.0: ModelSettingsModal の挙動検証。Save 押下で updateSimulatorConfig
// に値が流れ、不正値はエラー表示で弾かれる。Stop time (t_end) はここでは
// 編集しない (= Toolbar 側) ことも担保。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModelSettingsModal } from "../src/components/ModelSettingsModal";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, string>) => {
      if (params) {
        return Object.entries(params).reduce(
          (acc, [n, v]) => acc.replace(`{{${n}}}`, v),
          k,
        );
      }
      return k;
    },
  }),
}));

function makeModel(): FlwModel {
  return {
    schema_version: "0.8",
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: makeModel(),
    editingPath: [],
    dirty: false,
  });
});

afterEach(() => {
  cleanup();
});

describe("ModelSettingsModal", () => {
  it("shows current simulator values as defaults", () => {
    render(<ModelSettingsModal onClose={() => {}} />);
    expect(
      (screen.getByTestId("model-settings-solver") as HTMLSelectElement).value,
    ).toBe("RK45");
    expect(
      (screen.getByTestId("model-settings-dt") as HTMLInputElement).value,
    ).toBe("0.01");
    expect(
      (screen.getByTestId("model-settings-rtol") as HTMLInputElement).value,
    ).toBe("0.001");
    expect(
      (screen.getByTestId("model-settings-atol") as HTMLInputElement).value,
    ).toBe("0.000001");
  });

  it("dt_base auto checkbox is checked when dt_base is null", () => {
    render(<ModelSettingsModal onClose={() => {}} />);
    const auto = screen.getByTestId(
      "model-settings-dt-base-auto",
    ) as HTMLInputElement;
    expect(auto.checked).toBe(true);
    // 数値入力欄は出ていない (= explicit でない)
    expect(screen.queryByTestId("model-settings-dt-base")).toBeNull();
  });

  it("toggling auto OFF reveals dt_base number input", () => {
    render(<ModelSettingsModal onClose={() => {}} />);
    const auto = screen.getByTestId(
      "model-settings-dt-base-auto",
    ) as HTMLInputElement;
    fireEvent.click(auto);
    expect(auto.checked).toBe(false);
    expect(screen.getByTestId("model-settings-dt-base")).toBeTruthy();
  });

  it("Save commits values to simulator config and calls onClose", () => {
    const onClose = vi.fn();
    render(<ModelSettingsModal onClose={onClose} />);

    fireEvent.change(screen.getByTestId("model-settings-solver"), {
      target: { value: "LSODA" },
    });
    fireEvent.change(screen.getByTestId("model-settings-dt"), {
      target: { value: "0.005" },
    });

    fireEvent.click(screen.getByTestId("model-settings-save"));

    const sim = useAppStore.getState().editingModel!.simulator;
    expect(sim.solver).toBe("LSODA");
    expect(sim.dt).toBe(0.005);
    // t_end は触らない (= toolbar 担当)
    expect(sim.t_end).toBe(10);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Save with invalid dt does not commit and shows error", () => {
    const onClose = vi.fn();
    render(<ModelSettingsModal onClose={onClose} />);

    fireEvent.change(screen.getByTestId("model-settings-dt"), {
      target: { value: "-1" },
    });
    fireEvent.click(screen.getByTestId("model-settings-save"));

    expect(onClose).not.toHaveBeenCalled();
    // alert 表示
    expect(screen.getByRole("alert")).toBeTruthy();
    // 元の値を保持
    expect(useAppStore.getState().editingModel!.simulator.dt).toBe(0.01);
  });

  it("explicit dt_base value is committed", () => {
    render(<ModelSettingsModal onClose={() => {}} />);
    // auto OFF にしてから値入れる
    fireEvent.click(screen.getByTestId("model-settings-dt-base-auto"));
    fireEvent.change(screen.getByTestId("model-settings-dt-base"), {
      target: { value: "0.002" },
    });
    fireEvent.click(screen.getByTestId("model-settings-save"));
    expect(useAppStore.getState().editingModel!.simulator.dt_base).toBe(0.002);
  });

  it("auto checked → dt_base saved as null even if previous value was non-null", () => {
    const m = makeModel();
    m.simulator.dt_base = 0.003;
    useAppStore.setState({ editingModel: m, editingPath: [], dirty: false });

    render(<ModelSettingsModal onClose={() => {}} />);
    // 初期は auto=false (値あったので)
    const auto = screen.getByTestId(
      "model-settings-dt-base-auto",
    ) as HTMLInputElement;
    expect(auto.checked).toBe(false);
    // auto に切替
    fireEvent.click(auto);
    fireEvent.click(screen.getByTestId("model-settings-save"));
    expect(useAppStore.getState().editingModel!.simulator.dt_base).toBeNull();
  });
});
