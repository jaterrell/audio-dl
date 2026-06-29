import { useSettings } from "@/hooks/use-settings";
import type { ThemePref } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTS: { value: ThemePref; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ThemeToggle() {
  const { settings, setTheme } = useSettings();
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex gap-0.5 rounded-[var(--radius-md)] border border-[var(--border)] p-0.5"
    >
      {OPTS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={settings.theme === o.value}
          onClick={() => setTheme(o.value)}
          className={cn(
            "rounded-[var(--radius-sm)] px-2.5 py-1 text-xs cursor-pointer transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
            settings.theme === o.value
              ? "bg-[var(--surface-strong)] text-[var(--text)]"
              : "text-[var(--text-2)] hover:text-[var(--text)]",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
