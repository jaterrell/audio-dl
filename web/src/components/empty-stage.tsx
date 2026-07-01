import { AlbumArt } from "./album-art";
import type { HistoryItem } from "@/lib/types";

interface EmptyStageProps {
  latest: HistoryItem | null;
}

export function EmptyStage({ latest }: EmptyStageProps) {
  if (!latest) {
    return (
      <div className="grid place-items-center min-h-[300px] text-center px-8">
        <p className="text-[var(--text-2)] text-base">
          Paste a URL to get started.
        </p>
      </div>
    );
  }
  return (
    <div className="grid place-items-center px-8 pt-7 pb-4">
      <AlbumArt thumbId={latest.thumb_id} size={240} />
      <div className="text-center mt-6">
        <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--text-2)] mb-2">
          Last added
        </div>
        <h2 className="text-[22px] font-bold tracking-[-0.02em] truncate max-w-[80vw] mx-auto">
          {latest.title ?? latest.url}
        </h2>
        {latest.artist && <p className="text-[var(--text-2)] text-sm mt-1">{latest.artist}</p>}
      </div>
    </div>
  );
}
