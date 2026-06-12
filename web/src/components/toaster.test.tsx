import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "./toaster";
import { toast, resetToastStore } from "@/lib/toast-store";

beforeEach(() => resetToastStore());

describe("Toaster", () => {
  it("renders a toast pushed onto the store", async () => {
    render(<Toaster />);
    act(() => {
      toast.success("Added to library");
    });
    expect(await screen.findByText("Added to library")).toBeInTheDocument();
  });

  it("renders the description", async () => {
    render(<Toaster />);
    act(() => {
      toast.success("Added to library", { description: "Tycho — Awake" });
    });
    expect(await screen.findByText("Tycho — Awake")).toBeInTheDocument();
  });

  it("fires the action's onClick", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Toaster />);
    act(() => {
      toast.success("Added", { action: { label: "Reveal", onClick } });
    });
    await user.click(await screen.findByRole("button", { name: "Reveal" }));
    expect(onClick).toHaveBeenCalled();
  });

  it("dismisses via the close button", async () => {
    const user = userEvent.setup();
    render(<Toaster />);
    act(() => {
      toast.info("Hello");
    });
    await screen.findByText("Hello");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    await waitFor(() => expect(screen.queryByText("Hello")).not.toBeInTheDocument());
  });

  it("renders no close button on a loading toast (sticky)", async () => {
    render(<Toaster />);
    act(() => {
      toast.loading("Queueing 3 downloads…");
    });
    await screen.findByText("Queueing 3 downloads…");
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });
});

describe("Toaster live-region a11y", () => {
  it("announces error toasts assertively", async () => {
    render(<Toaster />);
    act(() => {
      toast.error("Download failed");
    });
    await screen.findByText("Download failed");
    expect(document.querySelector('[aria-live="assertive"]')).not.toBeNull();
  });

  it("announces success toasts politely, not assertively", async () => {
    render(<Toaster />);
    act(() => {
      toast.success("Added to library");
    });
    await screen.findByText("Added to library");
    expect(document.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(document.querySelector('[aria-live="assertive"]')).toBeNull();
  });
});
