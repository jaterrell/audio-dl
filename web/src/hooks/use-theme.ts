import { useEffect, useSyncExternalStore } from "react";
import { useSettings } from "./use-settings";
import { resolveTheme, applyTheme, type Mode } from "@/lib/theme";

export function useTheme() {
  const { settings, setTheme } = useSettings();
  const pref = settings.theme;
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(resolveTheme(pref, mq.matches));
    update();
    if (pref === "system") {
      mq.addEventListener("change", update);
      return () => mq.removeEventListener("change", update);
    }
  }, [pref]);
  return { theme: pref, setTheme };
}

function getResolved(): Mode {
  return (document.documentElement.getAttribute("data-theme") as Mode) || "dark";
}

export function useResolvedTheme(): Mode {
  return useSyncExternalStore(
    (cb) => {
      const obs = new MutationObserver(cb);
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => obs.disconnect();
    },
    getResolved,
    () => "dark",
  );
}
