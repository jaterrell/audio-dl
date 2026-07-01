import { useState } from "react";
import { Button } from "./ui/button";
import { FormatPicker } from "./format-picker";
import { useSettings } from "@/hooks/use-settings";
import { postJobs } from "@/lib/api";
import { toast } from "@/lib/toast-store";
import { trackJob } from "@/lib/tracked-jobs";

export function UrlInput() {
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
    const plural = urls.length === 1 ? "" : "s";
    const req = postJobs(urls);
    toast.promise(req, {
      loading: `Queueing ${urls.length} download${plural}…`,
      // Count comes from the submission, not the response — POST /jobs
      // returns only {"job_id"}.
      success: `Queued ${urls.length} download${plural}`,
      error: "Couldn't queue download",
    });
    try {
      const r = await req;
      trackJob(r.job_id);
      setValue("");
    } catch {
      /* surfaced by the toast above */
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-4 sm:mx-8 mb-8 flex flex-col sm:grid sm:grid-cols-[1fr_auto_auto] gap-2 p-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-lg)]">
      <textarea
        rows={1}
        aria-label="URL to download"
        placeholder="Paste a URL to queue it next…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !submitting) {
            e.preventDefault();
            handleAdd();
          }
        }}
        className="focus-ring bg-transparent border-none text-[var(--text)] px-3 py-2 text-sm outline-none placeholder:text-[var(--text-3)] resize-none rounded-[var(--radius-md)]"
      />
      <FormatPicker value={settings.default_format} onChange={setDefaultFormat} />
      <Button onClick={handleAdd} disabled={submitting || !value.trim()}>
        Add
      </Button>
    </div>
  );
}
