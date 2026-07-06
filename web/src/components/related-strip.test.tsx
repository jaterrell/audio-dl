import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithToaster } from "@/test-utils/render";
import { resetToastStore } from "@/lib/toast-store";
import { resetTrackedJobs, useTrackedJobs } from "@/lib/tracked-jobs";
import { renderHook } from "@testing-library/react";
import { RelatedStrip } from "./related-strip";
import type { RelatedItem } from "@/lib/types";

vi.mock("@/lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/api")>();
  return { ...mod, postJobs: vi.fn(async () => ({ job_id: "job-new" })) };
});
import { postJobs } from "@/lib/api";

beforeEach(() => {
  resetToastStore();
  resetTrackedJobs();
  localStorage.clear();
  vi.mocked(postJobs).mockClear();
});

function items(n: number): RelatedItem[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `n${i}`,
    title: `Song ${i}`,
    artist: "Artist",
    platform: i % 2 ? ("soundcloud" as const) : ("youtube" as const),
    webpage_url: `https://example-platform/${i}`,
    duration: 60,
    thumb_id: null,
  }));
}

describe("RelatedStrip", () => {
  it("renders null when empty", () => {
    renderWithToaster(<RelatedStrip items={[]} />);
    expect(screen.queryByLabelText("Related music")).toBeNull();
    expect(screen.queryByText(/more like this/i)).toBeNull();
  });

  it("renders one tile per item with heading, platform label, and safe link attrs", () => {
    renderWithToaster(<RelatedStrip items={items(3)} />);
    expect(screen.getByText(/more like this/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("related-tile")).toHaveLength(3);
    expect(screen.getAllByText(/·\s*YouTube/)).not.toHaveLength(0);
    const link = screen.getAllByRole("link")[0];
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("href", "https://example-platform/0");
  });

  it("queue button posts the item URL in the default format and tracks the job", async () => {
    const user = userEvent.setup();
    renderWithToaster(<RelatedStrip items={items(1)} />);
    await user.click(screen.getByRole("button", { name: /download song 0/i }));
    await waitFor(() =>
      expect(postJobs).toHaveBeenCalledWith([
        { url: "https://example-platform/0", format: "m4a" },
      ])
    );
    const { result } = renderHook(() => useTrackedJobs());
    expect(result.current).toContain("job-new");
    expect(await screen.findByText(/queued/i)).toBeInTheDocument();
  });

  it("queue failure surfaces an error toast", async () => {
    vi.mocked(postJobs).mockRejectedValueOnce(new TypeError("net down"));
    const user = userEvent.setup();
    renderWithToaster(<RelatedStrip items={items(1)} />);
    await user.click(screen.getByRole("button", { name: /download song 0/i }));
    expect(await screen.findByText(/can't reach audio-dl/i)).toBeInTheDocument();
  });
});
