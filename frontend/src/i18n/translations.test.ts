import { describe, expect, it } from "vitest";
import { en, zhCN } from "./translations";

const allowedSharedValues = new Set([
  "EN",
  "中文",
  "Physics-GNN",
  "Fluent/CFD",
  "MAE",
  "RMSE",
  "MaxAE",
  "Spearman",
  "Inlet1",
  "Inlet2",
  "bend class",
  "selected restart",
  "Not Found",
  "Forward Prediction",
  "智能药物浓度预测平台",
  "bend class",
]);

describe("translations", () => {
  it("keeps Chinese and English translation key sets identical", () => {
    expect(flatKeys(en)).toEqual(flatKeys(zhCN));
  });

  it("does not contain null, undefined, or empty translation values", () => {
    for (const [key, value] of Object.entries(flatten(zhCN))) {
      expect(value, `zh-CN ${key}`).toBeTypeOf("string");
      expect(String(value).trim(), `zh-CN ${key}`).not.toBe("");
    }
    for (const [key, value] of Object.entries(flatten(en))) {
      expect(value, `en ${key}`).toBeTypeOf("string");
      expect(String(value).trim(), `en ${key}`).not.toBe("");
    }
  });

  it("does not leave full Chinese sentences in English translations or full English sentences in Chinese translations", () => {
    const zh = flatten(zhCN);
    const english = flatten(en);

    for (const key of Object.keys(zh)) {
      if (allowedSharedValues.has(zh[key]) || allowedSharedValues.has(english[key])) {
        continue;
      }
      expect(english[key], `en ${key}`).not.toBe(zh[key]);
    }
  });
});

function flatKeys(value: object) {
  return Object.keys(flatten(value)).sort();
}

function flatten(value: object, prefix = ""): Record<string, string> {
  return Object.entries(value).reduce<Record<string, string>>((acc, [key, entry]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (typeof entry === "string") {
      acc[nextKey] = entry;
    } else if (entry && typeof entry === "object") {
      Object.assign(acc, flatten(entry, nextKey));
    }
    return acc;
  }, {});
}
