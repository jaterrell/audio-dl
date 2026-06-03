import { useEffect, type RefObject } from "react";

export function useVibrant(ref: RefObject<HTMLImageElement | null>) {
  useEffect(() => {
    const img = ref.current;
    if (!img) return;
    let cancelled = false;

    async function extract() {
      if (!img) return;
      try {
        const { Vibrant } = await import("node-vibrant/node");
        if (cancelled) return;
        const palette = await Vibrant.from(img).getPalette();
        if (cancelled) return;
        const accent = palette.Vibrant?.hex ?? "#818cf8";
        const accent2 = palette.LightVibrant?.hex ?? palette.Vibrant?.hex ?? "#c084fc";
        const ambient = palette.DarkMuted?.hex ?? "#1a1a2e";
        document.documentElement.style.setProperty("--accent", accent);
        document.documentElement.style.setProperty("--accent-2", accent2);
        document.documentElement.style.setProperty("--ambient", `${ambient}40`);
      } catch (e) {
        console.warn("vibrant extraction failed", e);
      }
    }

    if (img.complete) {
      extract();
    } else {
      img.addEventListener("load", extract);
    }
    return () => {
      cancelled = true;
      img.removeEventListener("load", extract);
    };
  }, [ref]);
}
