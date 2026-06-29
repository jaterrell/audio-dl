import { useState } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Format } from "@/lib/types";

interface LibraryFiltersProps {
  search: string;
  formats: Format[];
  availableFormats: Format[];
  onSearchChange: (next: string) => void;
  onFormatsChange: (next: Format[]) => void;
}

export function LibraryFilters({
  search: initialSearch, formats, availableFormats,
  onSearchChange, onFormatsChange,
}: LibraryFiltersProps) {
  const [search, setSearch] = useState(initialSearch);

  function handleSearchChange(next: string) {
    setSearch(next);
    onSearchChange(next);
  }

  function toggle(f: Format) {
    onFormatsChange(formats.includes(f) ? formats.filter((x) => x !== f) : [...formats, f]);
  }
  return (
    <div className="mx-8 mt-4 mb-6 flex gap-3 items-center flex-wrap">
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)]" />
        <input
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Search by title or artist"
          className="focus-ring w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] pl-9 pr-3 py-2 rounded-[var(--radius-md)] text-sm outline-none placeholder:text-[var(--text-3)]"
        />
      </div>
      <div className="flex gap-1.5">
        {availableFormats.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => toggle(f)}
            className={cn(
              "focus-ring px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
              formats.includes(f)
                ? "bg-[var(--accent)] text-[var(--on-accent)]"
                : "bg-[var(--surface)] text-[var(--text-2)] border border-[var(--border)]"
            )}
          >
            {f}
          </button>
        ))}
      </div>
    </div>
  );
}
