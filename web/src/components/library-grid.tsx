import { AlbumArt } from "./album-art";
import { LibraryTileMenu } from "./library-tile-menu";
import { groupByDay } from "@/lib/group-by-day";
import type { HistoryItem } from "@/lib/types";

interface LibraryGridProps {
  items: HistoryItem[];
  onRemove: (url: string) => void;
  isFiltered?: boolean;
}

export function LibraryGrid({ items, onRemove, isFiltered = false }: LibraryGridProps) {
  if (items.length === 0) {
    return (
      <div className="px-8 py-16 text-center text-[var(--text-2)] text-base font-light">
        {isFiltered
          ? "No results. Try a different search or format filter."
          : "Nothing yet. Downloads will appear here once they finish."}
      </div>
    );
  }
  const groups = groupByDay(items);
  return (
    <div className="px-8 pb-12">
      {groups.map((g) => (
        <div key={g.label} className="mb-8">
          <h3 className="text-lg font-bold tracking-tight mb-4 sticky top-0 bg-[var(--bg)] py-2">{g.label}</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-3">
            {g.items.map((h) => (
              <LibraryTileMenu key={h.url} item={h} onRemove={onRemove}>
                <div data-testid="library-tile" className="cursor-context-menu">
                  <AlbumArt thumbId={h.thumb_id} size={140} className="!w-full !h-auto aspect-square" />
                  <div className="text-sm font-semibold mt-2 truncate">{h.title ?? h.url}</div>
                  {h.artist && <div className="text-xs text-[var(--text-3)] truncate">{h.artist}</div>}
                </div>
              </LibraryTileMenu>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
