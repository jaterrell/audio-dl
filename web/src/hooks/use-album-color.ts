import { useEffect } from "react";
import { extractPalette } from "@/lib/color";
import type { Mode } from "@/lib/theme";

const VARS = ["--accent", "--accent-2", "--ambient", "--on-accent"] as const;

/**
 * Drives the dynamic "Now Playing" accent from the current track's album art.
 * Extracts a contrast-clamped palette on every `src` change (and when the
 * resolved `mode` flips), writing it inline on `:root`. When there is no art,
 * it removes the inline overrides so the stylesheet's brand base shows through.
 */
export function useAlbumColor(src: string | null, mode: Mode): void {
  useEffect(() => {
    const root = document.documentElement;
    const reset = () => {
      for (const v of VARS) root.style.removeProperty(v);
    };

    if (!src) {
      reset();
      return;
    }

    let cancelled = false;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.referrerPolicy = "no-referrer";

    const apply = () => {
      if (cancelled) return;
      const p = extractPalette(img, mode);
      if (!p) {
        reset();
        return;
      }
      root.style.setProperty("--accent", p.accent);
      root.style.setProperty("--accent-2", p.accent2);
      root.style.setProperty("--ambient", p.ambient);
      root.style.setProperty("--on-accent", p.onAccent);
    };

    img.onload = apply;
    img.src = src;
    if (img.complete && img.naturalWidth) apply();

    return () => {
      cancelled = true;
      img.onload = null;
      reset();
    };
  }, [src, mode]);
}
