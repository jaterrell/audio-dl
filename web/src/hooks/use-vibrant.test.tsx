import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useVibrant } from "./use-vibrant";

vi.mock("node-vibrant/node", () => ({
  Vibrant: {
    from: () => ({
      getPalette: () => Promise.resolve({
        Vibrant: { hex: "#ff00ff" },
        LightVibrant: { hex: "#ff66ff" },
        DarkMuted: { hex: "#330033" },
      }),
    }),
  },
}));

describe("useVibrant", () => {
  it("sets --accent on :root when img loads", async () => {
    const img = document.createElement("img");
    img.src = "/thumbs/abc.jpg";
    document.body.appendChild(img);
    renderHook(() => useVibrant({ current: img }));
    img.dispatchEvent(new Event("load"));
    await new Promise((r) => setTimeout(r, 50));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#ff00ff");
  });
});
