import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
});

describe("App navigation", () => {
  it("renders forward and reverse entries on the home page", () => {
    renderApp("/");

    expect(screen.getAllByRole("link", { name: /正向预测|姝ｅ悜棰勬祴/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /反向设计|鍙嶅悜璁捐/ }).length).toBeGreaterThan(0);
  });

  it("renders the reverse page", () => {
    renderApp("/reverse");

    expect(screen.getByRole("heading", { name: "反向设计" })).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(8);
  });

  it("shows not found for unknown routes", () => {
    renderApp("/missing");

    expect(screen.getByRole("heading", { name: /页面不存在|椤甸潰/ })).toBeInTheDocument();
  });
});

function renderApp(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}
