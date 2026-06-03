import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { LibraryFilters } from "./library-filters";

describe("LibraryFilters", () => {
  it("calls onSearchChange on input", async () => {
    const onSearchChange = vi.fn();
    const user = userEvent.setup();
    const { getByPlaceholderText } = renderUI(
      <LibraryFilters search="" formats={[]} availableFormats={["mp3", "flac"]}
        onSearchChange={onSearchChange} onFormatsChange={() => {}} />
    );
    await user.type(getByPlaceholderText(/search/i), "mac");
    expect(onSearchChange).toHaveBeenLastCalledWith("mac");
  });

  it("toggles format filters", async () => {
    const onFormatsChange = vi.fn();
    const user = userEvent.setup();
    const { getByRole } = renderUI(
      <LibraryFilters search="" formats={[]} availableFormats={["mp3", "flac"]}
        onSearchChange={() => {}} onFormatsChange={onFormatsChange} />
    );
    await user.click(getByRole("button", { name: "flac" }));
    expect(onFormatsChange).toHaveBeenLastCalledWith(["flac"]);
  });
});
