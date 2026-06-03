import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { AlbumArt } from "./album-art";

describe("AlbumArt", () => {
  it("renders an img with the correct src when thumbId is provided", () => {
    const { container } = renderUI(<AlbumArt thumbId="abc123" size={48} />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("/thumbs/abc123.jpg");
    expect(img!.style.width).toBe("48px");
  });

  it("renders a fallback when thumbId is null", () => {
    const { container } = renderUI(<AlbumArt thumbId={null} size={48} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-testid='album-art-fallback']")).not.toBeNull();
  });

  it("replaces img with fallback on error", async () => {
    const { container, findByTestId } = renderUI(<AlbumArt thumbId="abc" size={48} />);
    const img = container.querySelector("img")!;
    img.dispatchEvent(new Event("error"));
    expect(await findByTestId("album-art-fallback")).toBeInTheDocument();
  });
});
