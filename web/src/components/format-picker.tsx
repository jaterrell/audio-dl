import { ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./ui/dropdown-menu";
import { ALL_FORMATS, type Format } from "@/lib/types";

interface FormatPickerProps {
  value: Format;
  onChange: (next: Format) => void;
}

const QUALITY_HINT: Record<Format, string> = {
  mp3: "320 kbps",
  m4a: "256 kbps",
  flac: "lossless",
  alac: "lossless",
  opus: "best",
  wav: "raw",
  mp4: "video",
};

export function FormatPicker({ value, onChange }: FormatPickerProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="px-3 py-2 rounded-[var(--radius-md)] bg-[var(--surface)] border border-[var(--border)] text-sm font-medium text-[var(--text-2)] inline-flex items-center gap-2 cursor-pointer"
        >
          {value} · {QUALITY_HINT[value]}
          <ChevronDown size={12} className="text-[var(--text-3)]" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {ALL_FORMATS.map((f) => (
          <DropdownMenuItem key={f} selected={f === value} onSelect={() => onChange(f)}>
            {f} <span className="text-[var(--text-3)] text-xs ml-auto">{QUALITY_HINT[f]}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
