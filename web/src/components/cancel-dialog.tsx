import { X } from "lucide-react";
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "./ui/alert-dialog";
import { cancelJob } from "@/lib/api";
import { toast } from "@/lib/toast-store";

interface CancelDialogProps {
  jobId: string;
  size?: "sm" | "md";
}

export function CancelDialog({ jobId, size = "md" }: CancelDialogProps) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <button
          type="button"
          aria-label="Cancel"
          className={
            size === "sm"
              ? "w-5 h-5 rounded-full bg-black/40 grid place-items-center text-white/80 hover:text-white opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity focus-ring"
              : "w-6 h-6 rounded-full bg-black/40 grid place-items-center text-white/80 hover:text-white opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity focus-ring"
          }
        >
          <X size={size === "sm" ? 12 : 14} />
        </button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle className="text-base font-semibold tracking-tight">
          Cancel this download?
        </AlertDialogTitle>
        <AlertDialogDescription className="text-sm text-[var(--text-2)] mt-2">
          The download will stop. Partial files will be removed.
        </AlertDialogDescription>
        <div className="flex justify-end gap-2 mt-5">
          <AlertDialogCancel className="focus-ring px-4 py-2 text-sm rounded-[var(--radius-md)] text-[var(--text-2)] hover:bg-[var(--surface)]">
            Keep
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() =>
              toast.promise(cancelJob(jobId), {
                loading: "Cancelling…",
                success: "Download cancelled",
                error: "Couldn't cancel — try again",
              })
            }
            className="focus-ring px-4 py-2 text-sm rounded-[var(--radius-md)] bg-[var(--accent)] text-[var(--on-accent)] font-medium"
          >
            Confirm cancel
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
