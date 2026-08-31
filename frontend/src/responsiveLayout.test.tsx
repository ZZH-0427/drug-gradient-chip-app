import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";
import { I18nProvider } from "./i18n/I18nProvider";
import styles from "./styles.css?raw";

afterEach(() => {
  cleanup();
});

describe("desktop responsive layout safeguards", () => {
  it("keeps the application shell and main page from creating horizontal page overflow", () => {
    expect(ruleFor("body")).toContain("overflow-x: clip");
    expect(ruleFor(".app-shell")).toContain("overflow-x: clip");
    expect(ruleFor("main")).toContain("overflow-x: clip");
    expect(ruleFor(".page-section")).toContain("min-width: 0");
    expect(styles).not.toContain("width: 100vw");
  });

  it("allows long Assistant messages to wrap without widening the chat layout", () => {
    expect(ruleFor(".chat-layout")).toContain("grid-template-columns: minmax(0, 1fr) minmax(280px, 380px)");
    expect(ruleFor(".chat-layout")).toContain("min-width: 0");
    expect(ruleFor(".chat-panel")).toContain("min-width: 0");
    expect(ruleFor(".chat-messages")).toContain("min-width: 0");
    expect(ruleFor(".chat-message")).toContain("white-space: pre-wrap");
    expect(ruleFor(".chat-message")).toContain("overflow-wrap: anywhere");
    expect(ruleFor(".chat-message")).toContain("word-break: break-word");
    expect(ruleFor(".chat-message p")).toContain("overflow-wrap: anywhere");
  });

  it("keeps the Assistant composer inside its container at narrow widths", () => {
    expect(ruleFor(".chat-composer")).toContain("grid-template-columns: minmax(0, 1fr) auto");
    expect(ruleFor(".chat-composer")).toContain("min-width: 0");
    expect(ruleFor(".chat-composer textarea")).toContain("min-width: 0");
    expect(ruleFor(".chat-composer textarea")).toContain("max-height: 220px");
    expect(ruleFor(".chat-composer textarea")).toContain("overflow-x: hidden");
    expect(mediaRuleFor("max-width: 760px", ".chat-composer")).toContain("grid-template-columns: 1fr");
  });

  it("uses responsive grids for summaries, Forward inputs, Reverse targets, and metrics", () => {
    expect(ruleFor(".form-grid")).toContain("repeat(auto-fit");
    expect(ruleFor(".form-grid.form-grid-wide")).toContain("repeat(auto-fit");
    expect(ruleFor(".summary-list")).toContain("repeat(auto-fit");
    expect(ruleFor(".metric-grid")).toContain("repeat(auto-fit");
    expect(ruleFor(".summary-list div")).toContain("min-width: 0");
    expect(ruleFor(".summary-list dd")).toContain("overflow-wrap: anywhere");
  });

  it("keeps responsive tables without forcing header words to break internally", () => {
    expect(ruleFor(".table-wrap")).toContain("overflow-x: clip");
    expect(ruleFor("table")).toContain("table-layout: fixed");
    expect(ruleFor("th,\ntd")).toContain("white-space: normal");
    expect(ruleFor("th,\ntd")).not.toContain("white-space: nowrap");
    expect(ruleFor("th")).toContain("overflow-wrap: normal");
    expect(ruleFor("th")).toContain("word-break: normal");
    expect(ruleFor("th")).toContain("hyphens: manual");
    expect(ruleFor("td")).toContain("overflow-wrap: anywhere");
    expect(ruleFor("td")).toContain("word-break: break-word");
    expect(ruleFor(".input-table")).toContain("min-width: 0");
    expect(ruleFor(".result-table")).toContain("min-width: 0");
    expect(ruleFor(".compact-table")).toContain("min-width: 0");
    expect(ruleFor(".reverse-target-wrap")).toContain("overflow-x: clip");
  });

  it("keeps key page components on responsive class names", () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter initialEntries={["/assistant"]}>
          <App />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(container.querySelector(".topbar")).toBeInTheDocument();
    expect(container.querySelector(".chat-layout")).toBeInTheDocument();
    expect(container.querySelector(".chat-panel")).toBeInTheDocument();
    expect(container.querySelector(".chat-messages")).toBeInTheDocument();
    expect(container.querySelector(".chat-composer")).toBeInTheDocument();
    expect(container.querySelector(".chat-side")).toBeInTheDocument();
  });

  it("keeps the Assistant summary responsive breakpoint single-column", () => {
    expect(mediaRuleFor("max-width: 980px", ".chat-layout")).toContain("grid-template-columns: 1fr");
    expect(mediaRuleFor("max-width: 980px", ".chat-message")).toContain("max-width: 100%");
  });

  it("keeps required long Assistant prompts inside wrapping message bubbles", () => {
    const longForwardPrompt =
      "\u6211\u60f3\u7b976\u4e2a\u82af\u7247\uff0c\u5165\u53e31\u9ad8\u6d53\u5ea6\u3002" +
      "\u7b2c\u4e00\u4e2a\u90095to4\uff0c\u5de6\u5bbd.261\uff0c\u53f3\u5bbd.138\uff0c\u5de6\u8ddd31\uff0c\u53f3\u8ddd25\uff1b" +
      "\u7b2c\u4e8c\u4e2a\u90094to2\uff0c\u5de6\u5bbd.089\uff0c\u53f3\u5bbd.04\uff0c\u5de6\u8ddd25\uff0c\u53f3\u8ddd13\uff1b" +
      "\u7b2c\u4e09\u4e2a\u90091to6\uff0c\u5de6\u5bbd.212\uff0c\u53f3\u5bbd.236\uff0c\u5de6\u8ddd7\uff0c\u53f3\u8ddd31\u3002";
    const longReversePrompt =
      "\u6211\u60f3\u505a\u53cd\u5411\u8bbe\u8ba1\uff0c\u9ad8\u6d53\u5ea6\u8d70\u5165\u53e32\uff0c" +
      "\u76ee\u6807\u6d53\u5ea6\u4f9d\u6b21\u662f0.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002";

    const { container } = render(
      <div className="chat-messages">
        <article className="chat-message chat-message-user">
          <p>{longForwardPrompt}</p>
        </article>
        <article className="chat-message chat-message-user">
          <p>{longReversePrompt}</p>
        </article>
      </div>,
    );

    expect(container.querySelectorAll(".chat-message-user")).toHaveLength(2);
    expect(container).toHaveTextContent(longForwardPrompt);
    expect(container).toHaveTextContent(longReversePrompt);
    expect(ruleFor(".chat-message")).toContain("overflow-wrap: anywhere");
  });
});

function ruleFor(selector: string): string {
  const matches = styles.matchAll(/(?:^|\n)(?<selector>[^@{}\n][^{}]*)\{(?<body>[^}]*)\}/gm);
  for (const match of matches) {
    if (match.groups?.selector.trim() === selector) {
      return match.groups.body;
    }
  }
  return "";
}

function mediaRuleFor(query: string, selector: string): string {
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(
    new RegExp(`@media\\s*\\(${escapedQuery}\\)\\s*\\{[\\s\\S]*?${escapedSelector}\\s*\\{(?<body>[^}]*)\\}`, "m"),
  );
  return match?.groups?.body ?? "";
}
