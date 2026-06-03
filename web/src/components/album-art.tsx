import { useState } from "react";
import { cn } from "@/lib/utils";

interface AlbumArtProps {
  thumbId: string | null | undefined;
  size: number;
  className?: string;
}

export function AlbumArt({ thumbId, size, className }: AlbumArtProps) {
  const [failed, setFailed] = useState(false);

  const style = { width: `${size}px`, height: `${size}px` };

  if (!thumbId || failed) {
    return (
      <div
        data-testid="album-art-fallback"
        style={style}
        className={cn(
          "rounded-[var(--radius-sm)] flex-shrink-0",
          "bg-gradient-to-br from-[var(--accent)]/30 to-[var(--accent-2)]/30",
          className
        )}
      />
    );
  }

  return (
    <img
      src={`/thumbs/${thumbId}.jpg`}
      alt=""
      crossOrigin="anonymous"
      referrerPolicy="no-referrer"
      style={style}
      className={cn(
        "rounded-[var(--radius-sm)] flex-shrink-0 object-cover",
        "shadow-[0_2px_12px_rgba(0,0,0,0.4)]",
        className
      )}
      onError={() => setFailed(true)}
    />
  );
}
