import { useRef } from "react";
import { AlbumArt } from "./album-art";
import { CancelDialog } from "./cancel-dialog";
import { useVibrant } from "@/hooks/use-vibrant";
import type { JobSnapshot } from "@/lib/types";

interface HeroStageProps {
  snapshot: JobSnapshot;
  activeCount: number;
}

export function HeroStage({ snapshot, activeCount }: HeroStageProps) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  useVibrant(imgRef);

  const u = snapshot.urls[0];
  if (!u) return null;
  const title = u.title ?? u.url;
  const artist = u.uploader ?? "";

  return (
    <div className="grid place-items-center px-8 pt-7 pb-4">
      <div className="relative group">
        <AlbumArt
          thumbId={u.thumb_id}
          size={240}
          className="!shadow-[0_24px_64px_rgba(0,0,0,0.55),0_0_100px_var(--ambient)]"
        />
        <div className="absolute top-2 right-2">
          <CancelDialog jobId={snapshot.job_id} />
        </div>
        {/* Off-screen image used by useVibrant for color extraction.
            AlbumArt has its own internal <img>; this duplicates it as a hidden
            element with a ref we can pass to the hook. */}
        <img
          ref={imgRef}
          src={u.thumb_id ? `/thumbs/${u.thumb_id}.jpg` : ""}
          alt=""
          crossOrigin="anonymous"
          referrerPolicy="no-referrer"
          className="absolute opacity-0 pointer-events-none w-0 h-0"
        />
      </div>
      <div className="text-center mt-6">
        <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--accent)] mb-2">
          Downloading · 1 of {activeCount}
        </div>
        <h2 className="text-[26px] font-bold tracking-[-0.025em] leading-tight mb-1">{title}</h2>
        {artist && <p className="text-[var(--text-2)] text-[15px] mb-6">{artist}</p>}
        <div className="w-full max-w-[460px] mx-auto">
          <div className="h-1 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-[width] duration-200"
              style={{
                width: `${u.progress_percent}%`,
                background: "linear-gradient(90deg, var(--accent), var(--accent-2))",
                boxShadow: "0 0 8px var(--accent)",
              }}
            />
          </div>
          <div className="flex justify-between text-xs text-[var(--text-3)] mt-2">
            <span>{u.speed ?? ""}</span>
            <span>{u.eta ?? ""}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
