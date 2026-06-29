import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { cva } from "class-variance-authority";
import { CheckCircle2, Info, Loader2, XCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToastVariant } from "@/lib/toast-store";

export const ToastProvider = ToastPrimitive.Provider;

export const ToastViewport = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Viewport>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Viewport
    ref={ref}
    className={cn(
      "fixed z-[100] flex flex-col gap-2.5 outline-none",
      "top-4 right-4 w-[380px] max-w-[calc(100vw-2rem)]",
      "max-sm:top-auto max-sm:bottom-0 max-sm:inset-x-0 max-sm:w-full max-sm:max-w-full",
      "max-sm:p-3 max-sm:pb-[calc(0.75rem+env(safe-area-inset-bottom))]",
      className,
    )}
    {...props}
  />
));
ToastViewport.displayName = "ToastViewport";

export const Toast = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Root
    ref={ref}
    className={cn(
      "toast relative flex items-start gap-3 rounded-[var(--radius-lg)] border p-3",
      "bg-[var(--popover)] border-[var(--border)] text-[var(--text)]",
      className,
    )}
    {...props}
  />
));
Toast.displayName = "Toast";

const ICON: Record<ToastVariant, React.ComponentType<{ size?: number; className?: string }>> = {
  info: Info,
  success: CheckCircle2,
  error: XCircle,
  loading: Loader2,
};

const iconChip = cva("flex-none grid place-items-center w-[30px] h-[30px] rounded-[var(--radius-md)]", {
  variants: {
    variant: {
      info: "bg-[var(--info-bg)] text-[var(--info)]",
      success: "bg-[var(--ok-bg)] text-[var(--ok)]",
      error: "bg-[var(--err-bg)] text-[var(--err)]",
      loading: "bg-[var(--surface-strong)] text-[var(--text-2)]",
    },
  },
  defaultVariants: { variant: "info" },
});

export function ToastIcon({ variant }: { variant: ToastVariant }) {
  const Icon = ICON[variant];
  return (
    <span className={cn(iconChip({ variant }))} aria-hidden="true">
      <Icon size={17} className={variant === "loading" ? "animate-spin" : undefined} />
    </span>
  );
}

export const ToastTitle = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Title>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Title
    ref={ref}
    className={cn("truncate text-[13.5px] font-medium leading-snug", className)}
    {...props}
  />
));
ToastTitle.displayName = "ToastTitle";

export const ToastDescription = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Description>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Description
    ref={ref}
    className={cn("mt-0.5 line-clamp-3 text-xs text-[var(--text-2)]", className)}
    {...props}
  />
));
ToastDescription.displayName = "ToastDescription";

export const ToastAction = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Action>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Action>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Action
    ref={ref}
    className={cn(
      "flex-none self-center rounded-[var(--radius-md)] border border-[var(--border)] px-2.5 py-1",
      "text-xs font-medium text-[var(--text)] hover:bg-[var(--surface)]",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
      className,
    )}
    {...props}
  />
));
ToastAction.displayName = "ToastAction";

export const ToastClose = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Close>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Close
    ref={ref}
    aria-label="Dismiss"
    className={cn("flex-none self-start rounded p-0.5 text-[var(--text-3)] hover:text-[var(--text)]", className)}
    {...props}
  >
    <X size={15} aria-hidden="true" />
  </ToastPrimitive.Close>
));
ToastClose.displayName = "ToastClose";
