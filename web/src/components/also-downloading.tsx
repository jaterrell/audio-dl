import { AlbumArt } from "./album-art";
import { CancelDialog } from "./cancel-dialog";
import type { JobSnapshot } from "@/lib/types";

interface AlsoDownloadingProps {
  jobs: JobSnapshot[];
  stageJobId?: string;
}

export function AlsoDownloading({ jobs, stageJobId }: AlsoDownloadingProps) {
  // One card per URL so every track in a multi-URL job is visible with its own
  // progress. Cancel is job-level, so it sits only on the first card of a job,
  // and not at all for the stage job (its cancel already lives on HeroStage).
  const cards = jobs.flatMap((j) =>
    j.urls.map((u, i) => ({ jobId: j.job_id, u, first: i === 0 && j.job_id !== stageJobId }))
  );
  if (cards.length === 0) return null;
  return (
    <div className="mx-8 mt-7 grid grid-cols-[90px_1fr] gap-4 items-center">
      <div className="text-right text-xs text-[var(--text-3)] font-medium">Also downloading</div>
      <div className="flex gap-2 overflow-x-auto">
        {cards.map(({ jobId, u, first }) => (
          <div
            key={`${jobId}-${u.url}`}
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
            {first && (
              <div className="absolute top-1 right-1">
                <CancelDialog jobId={jobId} size="sm" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
