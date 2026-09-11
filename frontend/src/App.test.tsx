import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { LOCALE_STORAGE_KEY } from "./i18n/locale";
import { renderWithI18n } from "./test/renderWithI18n";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("App localization", () => {
  it("defaults to Chinese and renders forward and reverse prediction entries", () => {
    renderApp("/");

    expect(screen.getAllByRole("link", { name: /正向预测/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /反向预测/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("group", { name: "切换界面语言" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe("智能药物浓度预测平台");
    expect(document.body.textContent).not.toContain("反向设计");
    expect(document.body.textContent).not.toContain("Reverse Design");
  });

  it("falls back to Chinese for invalid stored locale", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "broken");

    renderApp("/");

    expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "智能药物浓度预测平台" })).toBeInTheDocument();
  });

  it("switches to English, persists locale, and switches back without routing", async () => {
    const user = userEvent.setup();
    renderApp("/reverse");

    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(window.location.pathname).toBe("/");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(screen.getByRole("group", { name: "Switch interface language" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Reverse Prediction" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
    expect(document.title).toBe("Reverse Prediction | 智能药物浓度预测平台");

    await user.click(screen.getByRole("button", { name: "中文" }));

    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("zh-CN");
    expect(screen.getByRole("heading", { name: "反向预测" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("restores English after rerender from localStorage", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");

    renderApp("/missing");

    expect(screen.getByRole("heading", { name: "Page Not Found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Home" })).toBeInTheDocument();
    expect(document.title).toBe("Page Not Found | 智能药物浓度预测平台");
  });

  it("supports keyboard operation for the language switcher", async () => {
    const user = userEvent.setup();
    renderApp("/");

    screen.getByRole("button", { name: "EN" }).focus();
    await user.keyboard("{Enter}");

    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(screen.getByRole("heading", { name: "智能药物浓度预测平台" })).toBeInTheDocument();
  });

  it("continues to render in Chinese when localStorage read or write fails", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const user = userEvent.setup();

    renderApp("/");
    expect(screen.getByRole("heading", { name: "智能药物浓度预测平台" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "EN" }));
    expect(screen.getByRole("heading", { name: "智能药物浓度预测平台" })).toBeInTheDocument();
    expect(getItem).toHaveBeenCalled();
    expect(setItem).toHaveBeenCalled();
  });
});

function renderApp(initialPath: string) {
  renderWithI18n(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}
