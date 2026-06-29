import { describe, it, expect, afterEach } from "vitest";
import { resolveTheme, applyTheme } from "./theme";

afterEach(() => document.documentElement.removeAttribute("data-theme"));

describe("resolveTheme", () => {
  it("maps system to dark/light by prefersDark", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
  it("returns explicit preferences unchanged", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("applyTheme", () => {
  it("sets data-theme on the root element", () => {
    applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
