import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface AlbumArtProps {
  thumbId: string | null | undefined;
  size: number;
  className?: string;
}

function radiusFor(size: number): string {
  if (size >= 200) return "rounded-[var(--radius-lg)]";
  if (size >= 80) return "rounded-[var(--radius-md)]";
  return "rounded-[var(--radius-sm)]";
}

export function AlbumArt({ thumbId, size, className }: AlbumArtProps) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  const style = { width: `${size}px`, height: `${size}px` };
  const radius = radiusFor(size);

  // Reset on src change; catch already-cached images (onLoad won't fire for those).
  useEffect(() => {
    setLoaded(false);
    if (imgRef.current?.complete && imgRef.current.naturalWidth > 0) setLoaded(true);
  }, [thumbId]);

  if (!thumbId || failed) {
    return (
      <div
        data-testid="album-art-fallback"
        style={style}
        className={cn(
          radius,
          "flex-shrink-0",
          "bg-gradient-to-br from-[var(--brand)]/30 to-[var(--brand-2)]/30",
          className
        )}
      />
    );
  }

  return (
    <img
      ref={imgRef}
      src={`/thumbs/${thumbId}.jpg`}
      alt=""
      crossOrigin="anonymous"
      referrerPolicy="no-referrer"
      style={style}
      onLoad={() => setLoaded(true)}
      onError={() => setFailed(true)}
      className={cn(
        radius,
        "flex-shrink-0 object-cover",
        "shadow-[0_2px_12px_rgba(0,0,0,0.4)]",
        "transition-opacity duration-300",
        loaded ? "opacity-100" : "opacity-0",
        className
      )}
    />
  );
}
