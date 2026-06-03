import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useJobEvents } from "@/hooks/use-job-events";
import { useHistory } from "@/hooks/use-history";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function JobTracker({ jobId }: { jobId: string }) {
  useJobEvents(jobId);
  const queryClient = useQueryClient();
  const { data } = useQuery<JobSnapshot>({ queryKey: ["job", jobId], enabled: false });
  const { addItem } = useHistory();

  useEffect(() => {
    if (!data) return;
    if (!TERMINAL.includes(data.state)) return;
    for (const u of data.urls) {
      if (u.state === "completed") {
        addItem({
          url: u.url,
          title: null,
          artist: null,
          media_format: u.media_format,
          paths: u.paths,
          thumb_id: u.thumb_id,
          added_at: Date.now(),
        });
      }
    }
    setTimeout(() => queryClient.removeQueries({ queryKey: ["job", jobId] }), 1500);
  }, [data, addItem, jobId, queryClient]);

  return null;
}
