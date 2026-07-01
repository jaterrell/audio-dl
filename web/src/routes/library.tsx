import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useHistory } from "@/hooks/use-history";
import { LibraryFilters } from "@/components/library-filters";
import { LibraryGrid } from "@/components/library-grid";
import type { Format } from "@/lib/types";

export const Route = createFileRoute("/library")({ component: LibraryScreen });

function LibraryScreen() {
  const { history, removeItem } = useHistory();
  const [search, setSearch] = useState("");
  const [formats, setFormats] = useState<Format[]>([]);

  const availableFormats = useMemo(
    () => Array.from(new Set(history.map((h) => h.media_format))) as Format[],
    [history]
  );

  const filtered = useMemo(
    () => history.filter((h) => {
      if (formats.length > 0 && !formats.includes(h.media_format)) return false;
      if (search) {
        const needle = search.toLowerCase();
        const hay = `${h.title ?? ""} ${h.artist ?? ""} ${h.url}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    }),
    [history, search, formats]
  );

  return (
    <>
      <LibraryFilters
        search={search} formats={formats} availableFormats={availableFormats}
        onSearchChange={setSearch} onFormatsChange={setFormats}
      />
      <LibraryGrid
        items={filtered}
        onRemove={removeItem}
        isFiltered={search.trim() !== "" || formats.length > 0}
      />
    </>
  );
}
