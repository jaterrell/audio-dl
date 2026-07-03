import { FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from "./ui/context-menu";
import { describeError, reveal, postJobs } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";
import { toast } from "@/lib/toast-store";
import { trackJob } from "@/lib/tracked-jobs";

interface LibraryTileMenuProps {
  item: HistoryItem;
  onRemove: (url: string) => void;
  children: ReactNode;
}

export function LibraryTileMenu({ item, onRemove, children }: LibraryTileMenuProps) {
  async function handleReveal() {
    if (!item.paths[0]) return;
    try {
      await reveal(item.paths[0]);
    } catch (err) {
      const { title, description } = describeError(err, "Couldn't reveal file");
      toast.error(title, { description });
    }
  }
  async function handleReDownload() {
    try {
      const r = await postJobs([{ url: item.url, format: item.media_format }]);
      // Track it so a JobTracker mounts (SSE progress, completion toast, history).
      trackJob(r.job_id);
      toast.success("Re-downloading…", { description: item.title ?? item.url });
    } catch (err) {
      const { title, description } = describeError(err, "Couldn't start re-download");
      toast.error(title, { description });
    }
  }
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={handleReveal} disabled={!item.paths[0]}>
          <FolderOpen size={14} /> Reveal in Finder
        </ContextMenuItem>
        <ContextMenuItem onSelect={handleReDownload}>
          <RefreshCw size={14} /> Re-download
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => onRemove(item.url)}>
          <Trash2 size={14} /> Dismiss from history
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
