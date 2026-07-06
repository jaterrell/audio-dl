import { Download } from "lucide-react";
import { AlbumArt } from "./album-art";
import { Button } from "./ui/button";
import { postJobs, describeError } from "@/lib/api";
import { trackJob } from "@/lib/tracked-jobs";
import { useSettings } from "@/hooks/use-settings";
import { toast } from "@/lib/toast-store";
import type { RelatedItem } from "@/lib/types";

const PLATFORM_LABEL: Record<RelatedItem["platform"], string> = {
  youtube: "YouTube",
  soundcloud: "SoundCloud",
};

export function RelatedStrip({ items }: { items: RelatedItem[] }) {
  const { settings } = useSettings();
  if (items.length === 0) return null;

  async function queue(item: RelatedItem) {
    try {
      const r = await postJobs([
        { url: item.webpage_url, format: settings.default_format },
      ]);
      trackJob(r.job_id);
      toast.success("Queued", { description: item.title });
    } catch (err) {
      const { title, description } = describeError(err, "Couldn't queue download");
      toast.error(title, { description });
    }
  }

  return (
    <section aria-label="Related music" className="mx-8 mt-7 enter-fade">
      <div className="text-xs text-[var(--text-3)] font-medium mb-2">
        More like this
      </div>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {items.map((item) => (
          <div
            key={`${item.platform}-${item.id}`}
            data-testid="related-tile"
            className="group relative w-[132px] flex-shrink-0"
          >
            <a
              href={item.webpage_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block focus-ring rounded-[var(--radius-md)]"
            >
              <AlbumArt thumbId={item.thumb_id} size={120} />
              <div className="text-xs font-medium truncate mt-1.5">
                {item.title}
              </div>
              <div className="text-[11px] text-[var(--text-3)] truncate">
                {item.artist ? `${item.artist} · ` : ""}
                {PLATFORM_LABEL[item.platform]}
              </div>
            </a>
            {/* Sibling of the anchor, never nested inside it — nested
                interactive elements are invalid HTML. */}
            <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Download ${item.title}`}
                className="h-7 w-7 bg-[var(--surface)]/80 backdrop-blur-sm focus-ring"
                onClick={() => queue(item)}
              >
                <Download size={14} />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
