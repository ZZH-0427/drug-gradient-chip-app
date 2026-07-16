import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./baseUrl";

describe("resolveApiBaseUrl", () => {
  it("uses local backend for development without explicit configuration", () => {
    expect(resolveApiBaseUrl({ configuredUrl: undefined, isDevelopment: true })).toBe(
      "http://127.0.0.1:8000",
    );
  });

  it("uses same-origin relative requests for production without explicit configuration", () => {
    expect(resolveApiBaseUrl({ configuredUrl: undefined, isDevelopment: false })).toBe("");
  });

  it("prefers explicit VITE_API_BASE_URL", () => {
    expect(
      resolveApiBaseUrl({
        configuredUrl: "http://example.test:9000",
        isDevelopment: false,
      }),
    ).toBe("http://example.test:9000");
  });

  it("normalizes trailing slashes", () => {
    expect(
      resolveApiBaseUrl({
        configuredUrl: "http://example.test:9000///",
        isDevelopment: true,
      }),
    ).toBe("http://example.test:9000");
  });

  it("treats blank explicit configuration as unset", () => {
    expect(resolveApiBaseUrl({ configuredUrl: "   ", isDevelopment: false })).toBe("");
  });
});
