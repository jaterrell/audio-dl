import { AlbumArt } from "./album-art";
import type { JobSnapshot } from "@/lib/types";

interface QueueProps {
  jobs: JobSnapshot[];
}

export function Queue({ jobs }: QueueProps) {
  if (jobs.length === 0) return null;
  return (
    <div className="mx-8 mt-7">
      <div className="flex justify-between items-baseline mb-3">
        <div className="text-base font-bold tracking-[-0.015em]">Up next</div>
        <div className="text-sm text-[var(--text-3)]">{jobs.length} queued</div>
      </div>
      {jobs.map((j) => {
        const u = j.urls[0];
        if (!u) return null;
        return (
          <div
            key={j.job_id}
            data-testid="queue-row"
            className="grid grid-cols-[40px_1fr_auto] gap-3 items-center p-2 rounded-[var(--radius-md)] hover:bg-white/[0.03]"
          >
            <AlbumArt thumbId={u.thumb_id} size={40} />
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{u.title ?? u.url}</div>
              {u.uploader && (
                <div className="text-xs text-[var(--text-3)] truncate">{u.uploader}</div>
              )}
            </div>
            <span className="text-xs text-[var(--text-2)] bg-[var(--surface)] px-2 py-0.5 rounded-full font-medium">
              {u.media_format}
            </span>
          </div>
        );
      })}
    </div>
  );
}
