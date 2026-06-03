import { useState } from "react";
import { Button } from "./ui/button";
import { FormatPicker } from "./format-picker";
import { useSettings } from "@/hooks/use-settings";
import { postJobs } from "@/lib/api";

interface UrlInputProps {
  onJobCreated: (jobId: string) => void;
}

export function UrlInput({ onJobCreated }: UrlInputProps) {
  const { settings, setDefaultFormat } = useSettings();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleAdd() {
    const lines = value
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length === 0) return;
    const urls = lines.map((url) => ({ url, format: settings.default_format }));
    setSubmitting(true);
    try {
      const r = await postJobs(urls);
      onJobCreated(r.job_id);
      setValue("");
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-7 mb-8 grid grid-cols-[1fr_auto_auto] gap-2 p-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-lg)]">
      <textarea
        rows={1}
        placeholder="Paste a URL to queue it next…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !submitting) {
            e.preventDefault();
            handleAdd();
          }
        }}
        className="bg-transparent border-none text-[var(--text)] px-3 py-2 text-sm outline-none placeholder:text-[var(--text-3)] resize-none"
      />
      <FormatPicker value={settings.default_format} onChange={setDefaultFormat} />
      <Button onClick={handleAdd} disabled={submitting || !value.trim()}>
        Add
      </Button>
    </div>
  );
}
