import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderUI, renderWithToaster } from "@/test-utils/render";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { CancelDialog } from "./cancel-dialog";
import { resetToastStore } from "@/lib/toast-store";

beforeEach(() => resetToastStore());

describe("CancelDialog", () => {
  it("renders the trigger button", () => {
    const { getByRole } = renderUI(<CancelDialog jobId="job-1" />);
    expect(getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("calls cancelJob on confirm", async () => {
    const cancelHandler = vi.fn(() => HttpResponse.json({ cancelled: true }));
    server.use(http.post("/jobs/job-1/cancel", cancelHandler));
    const user = userEvent.setup();
    const { getByRole, findByRole } = renderUI(<CancelDialog jobId="job-1" />);
    await user.click(getByRole("button", { name: /cancel/i }));
    await user.click(await findByRole("button", { name: /confirm/i }));
    expect(cancelHandler).toHaveBeenCalled();
  });

  it("surfaces an error toast when the cancel request fails", async () => {
    server.use(http.post("/jobs/job-1/cancel", () => HttpResponse.json({}, { status: 500 })));
    const user = userEvent.setup();
    const { getByRole, findByRole } = renderWithToaster(<CancelDialog jobId="job-1" />);
    await user.click(getByRole("button", { name: /cancel/i }));
    await user.click(await findByRole("button", { name: /confirm/i }));
    expect(await screen.findByText(/couldn't cancel/i)).toBeInTheDocument();
  });
});
