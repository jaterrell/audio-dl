export type Mode = "light" | "dark";
export type ThemePref = "system" | "light" | "dark";

export function resolveTheme(pref: ThemePref, prefersDark: boolean): Mode {
  if (pref === "system") return prefersDark ? "dark" : "light";
  return pref;
}

export function applyTheme(mode: Mode): void {
  document.documentElement.setAttribute("data-theme", mode);
}
