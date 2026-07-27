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

    expect(screen.getAllByRole("link", { name: /正向预测/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /反向设计/ }).length).toBeGreaterThan(0);
  });

  it("renders the reverse page", () => {
    renderApp("/reverse");

    expect(screen.getByRole("heading", { name: "反向设计" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);
  });

  it("shows not found for unknown routes", () => {
    renderApp("/missing");

    expect(screen.getByRole("heading", { name: /页面不存在/ })).toBeInTheDocument();
  });
});

function renderApp(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}
