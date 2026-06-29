import { describe, it, expect } from "vitest";
import { buttonVariants } from "./button";

describe("buttonVariants", () => {
  it("default variant uses on-accent text and a colored focus ring", () => {
    const cls = buttonVariants({ variant: "default" });
    expect(cls).toContain("text-[var(--on-accent)]");
    expect(cls).toContain("focus-visible:ring-[var(--accent)]");
  });
});
