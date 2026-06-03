import { AlbumArt } from "./album-art";
import { CancelDialog } from "./cancel-dialog";
import type { JobSnapshot } from "@/lib/types";

interface AlsoDownloadingProps {
  jobs: JobSnapshot[];
}

export function AlsoDownloading({ jobs }: AlsoDownloadingProps) {
  if (jobs.length === 0) return null;
  return (
    <div className="mx-8 mt-7 grid grid-cols-[90px_1fr] gap-4 items-center">
      <div className="text-right text-xs text-[var(--text-3)] font-medium">Also downloading</div>
      <div className="flex gap-2 overflow-x-auto">
        {jobs.map((j) => {
          const u = j.urls[0];
          if (!u) return null;
          return (
            <div
              key={j.job_id}
              data-testid="also-card"
              className="group relative flex items-center gap-2.5 p-2 pr-3 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-md)] flex-1 min-w-[200px]"
            >
              <AlbumArt thumbId={u.thumb_id} size={32} />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium truncate">{u.title ?? u.url}</div>
                <div className="h-0.5 bg-white/7 rounded-full overflow-hidden mt-1">
                  <div
                    className="h-full rounded-full transition-[width] duration-200"
                    style={{ width: `${u.progress_percent}%`, background: "var(--accent)" }}
                  />
                </div>
              </div>
              <div className="absolute top-1 right-1">
                <CancelDialog jobId={j.job_id} size="sm" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
