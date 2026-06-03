import { FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from "./ui/context-menu";
import { reveal, postJobs } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";

interface LibraryTileMenuProps {
  item: HistoryItem;
  onRemove: (url: string) => void;
  children: ReactNode;
}

export function LibraryTileMenu({ item, onRemove, children }: LibraryTileMenuProps) {
  async function handleReveal() {
    if (item.paths[0]) {
      try { await reveal(item.paths[0]); } catch (e) { console.error(e); }
    }
  }
  async function handleReDownload() {
    try { await postJobs([{ url: item.url, format: item.media_format }]); }
    catch (e) { console.error(e); }
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
