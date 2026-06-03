import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { FormatPicker } from "./format-picker";

describe("FormatPicker", () => {
  it("renders the current value", () => {
    const { getByRole } = renderUI(<FormatPicker value="m4a" onChange={() => {}} />);
    expect(getByRole("button")).toHaveTextContent(/m4a/i);
  });

  it("calls onChange when a different format is selected", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { getByRole, findByText } = renderUI(<FormatPicker value="m4a" onChange={onChange} />);
    await user.click(getByRole("button"));
    await user.click(await findByText("flac"));
    expect(onChange).toHaveBeenCalledWith("flac");
  });
});
