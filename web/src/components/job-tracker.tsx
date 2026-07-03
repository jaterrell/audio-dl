import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useJobEvents } from "@/hooks/use-job-events";
import { useHistory } from "@/hooks/use-history";
import { describeError, reveal, postJobs } from "@/lib/api";
import { toast } from "@/lib/toast-store";
import { untrackJob } from "@/lib/tracked-jobs";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function JobTracker({ jobId, onJobCreated }: { jobId: string; onJobCreated?: (id: string) => void }) {
  useJobEvents(jobId);
  const queryClient = useQueryClient();
  const { data } = useQuery<JobSnapshot>({ queryKey: ["job", jobId], enabled: false });
  const { addItem } = useHistory();
  const toastedRef = useRef(false);

  useEffect(() => {
    if (!data) return;
    if (!TERMINAL.includes(data.state)) return;
    if (toastedRef.current) return;
    toastedRef.current = true;

    for (const u of data.urls) {
      if (u.state === "completed") {
        addItem({
          url: u.url,
          title: u.title,
          artist: u.uploader,
          media_format: u.media_format,
          paths: u.paths,
          thumb_id: u.thumb_id,
          added_at: Date.now(),
        });
        toast.success("Added to library", {
          description: u.title ?? u.url,
          action: u.paths[0]
            ? {
                label: "Reveal",
                onClick: () => {
                  reveal(u.paths[0]).catch((err) => {
                    const { title, description } = describeError(err, "Couldn't reveal file");
                    toast.error(title, { description });
                  });
                },
              }
            : undefined,
        });
      } else if (u.state === "failed") {
        const failId = `fail-${jobId}-${u.url}`;
        toast.error("Download failed", {
          id: failId,
          description: u.error ?? u.title ?? u.url,
          action: {
            label: "Retry",
            onClick: () => {
              // Clear the sticky failure toast so it doesn't linger beside the
              // new re-downloading toast.
              toast.dismiss(failId);
              postJobs([{ url: u.url, format: u.media_format }])
                .then((r) => {
                  onJobCreated?.(r.job_id);
                  toast.success("Re-downloading…", { description: u.title ?? u.url });
                })
                .catch((err) => {
                  const { title, description } = describeError(err, "Couldn't start re-download");
                  toast.error(title, { description });
                });
            },
          },
        });
      }
    }

    setTimeout(() => {
      queryClient.removeQueries({ queryKey: ["job", jobId] });
      untrackJob(jobId);
    }, 1500);
  }, [data, addItem, jobId, queryClient, onJobCreated]);

  return null;
}
