import { useEffect } from "react";
import {
  ToastProvider,
  ToastViewport,
  Toast,
  ToastIcon,
  ToastTitle,
  ToastDescription,
  ToastAction,
  ToastClose,
} from "@/components/ui/toast";
import { useToasts, toast as toastApi, setMaxToasts } from "@/lib/toast-store";

// jsdom has no matchMedia; default to "right" when unavailable.
function swipeDirection(): "right" | "down" {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "right";
  return window.matchMedia("(max-width: 639px)").matches ? "down" : "right";
}

export function Toaster({ max = 4 }: { max?: number }) {
  const toasts = useToasts();

  useEffect(() => {
    setMaxToasts(max);
  }, [max]);

  return (
    <ToastProvider swipeDirection={swipeDirection()}>
      {toasts.map((t) => (
        <Toast
          key={t.id}
          type={t.variant === "error" ? "foreground" : "background"}
          duration={Number.isFinite(t.duration) ? t.duration : 86_400_000}
          onOpenChange={(open) => {
            if (!open) toastApi.dismiss(t.id);
          }}
        >
          <ToastIcon variant={t.variant} />
          <div className="min-w-0 flex-1">
            <ToastTitle>{t.title}</ToastTitle>
            {t.description ? <ToastDescription title={t.description}>{t.description}</ToastDescription> : null}
          </div>
          {t.action ? (
            <ToastAction altText={t.action.label} onClick={t.action.onClick}>
              {t.action.label}
            </ToastAction>
          ) : null}
          {t.variant !== "loading" ? <ToastClose /> : null}
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
