# Toast Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable, accessible toast/notification layer to the `web/` React app and wire it into the spots that currently fail silently.

**Architecture:** A Radix-backed `ui/toast.tsx` (styled wrappers, same pattern as `ui/alert-dialog.tsx`), an imperative `toast.*` store in `lib/toast-store.ts` (module-level `useSyncExternalStore`, mirroring `use-history.ts`), and a `<Toaster>` renderer mounted once in `__root.tsx`. Integrations replace swallowed `console.error`s and surface download completion/failure.

**Tech Stack:** React 19, TypeScript, `@radix-ui/react-toast`, Tailwind v4, `class-variance-authority`, lucide-react, Vitest + Testing Library + MSW.

**Spec:** [docs/superpowers/specs/2026-06-09-web-ui-toast-notifications-design.md](../specs/2026-06-09-web-ui-toast-notifications-design.md)

**Conventions:**
- All `npm`/test commands run from `web/`.
- Single test file: `npm test -- src/path/to/file.test.ts`.
- Typecheck: `npx tsc -b`. Lint: `npm run lint`.
- Implementation happens on a feature branch off `main` (the spec is already on `origin/main`). Commit only the files each task names — the working tree has unrelated untracked files; never `git add -A`.

---

## Task 0: Branch + dependency + tokens + animations

**Files:**
- Modify: `web/package.json` (via `npm install`)
- Modify: `web/src/styles/tokens.css`
- Modify: `web/src/styles/globals.css`

- [ ] **Step 1: Create the feature branch**

```bash
git checkout main && git pull origin main
git checkout -b feat/web-toast-notifications
```

- [ ] **Step 2: Install the Radix toast primitive**

Run (from `web/`):

```bash
npm install @radix-ui/react-toast
```

Expected: `package.json` `dependencies` gains `"@radix-ui/react-toast": "^1.2.x"`; `package-lock.json` updates.

- [ ] **Step 3: Add semantic color tokens**

In `web/src/styles/tokens.css`, add inside `:root`, immediately after the radii block (before the closing `}`):

```css

  /* semantic status colors — accent is hijacked by useVibrant, so it can't carry meaning */
  --ok: #34d399;   --ok-bg: rgb(52 211 153 / 0.14);
  --err: #f87171;  --err-bg: rgb(248 113 113 / 0.14);
  --warn: #fbbf24; --warn-bg: rgb(251 191 36 / 0.14);
  --info: #60a5fa; --info-bg: rgb(96 165 250 / 0.14);
```

- [ ] **Step 4: Add toast animations**

Append to the end of `web/src/styles/globals.css`:

```css

/* toast enter/exit — keyed off Radix data-state / data-swipe */
@keyframes toast-in-x { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }
@keyframes toast-out-x { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(12px); } }
@keyframes toast-in-y { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toast-out-y { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(16px); } }

.toast[data-state="open"] { animation: toast-in-x 160ms cubic-bezier(0.16, 1, 0.3, 1); }
.toast[data-state="closed"] { animation: toast-out-x 120ms ease-in; }
.toast[data-swipe="move"] { transform: translateX(var(--radix-toast-swipe-move-x)); }
.toast[data-swipe="cancel"] { transform: translateX(0); transition: transform 160ms ease-out; }
.toast[data-swipe="end"] { animation: toast-out-x 120ms ease-in; }

@media (max-width: 639px) {
  .toast[data-state="open"] { animation-name: toast-in-y; }
  .toast[data-state="closed"], .toast[data-swipe="end"] { animation-name: toast-out-y; }
  .toast[data-swipe="move"] { transform: translateY(var(--radix-toast-swipe-move-y)); }
}

@media (prefers-reduced-motion: reduce) {
  .toast[data-state], .toast[data-swipe] { animation: none !important; transition: none !important; }
}
```

- [ ] **Step 5: Verify the app still builds**

Run: `npx tsc -b`
Expected: PASS (no type errors; the new dep resolves).

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/src/styles/tokens.css web/src/styles/globals.css
git commit -m "feat(web): add toast dependency, semantic tokens, animations"
```

---

## Task 1: Toast store — add / dismiss / cap / update

**Files:**
- Create: `web/src/lib/toast-store.ts`
- Test: `web/src/lib/toast-store.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/toast-store.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { toast, getToasts, resetToastStore, setMaxToasts } from "./toast-store";

beforeEach(() => resetToastStore());

describe("toast store", () => {
  it("adds a toast and returns its id", () => {
    const id = toast.success("Saved");
    expect(typeof id).toBe("string");
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "success", title: "Saved" });
  });

  it("dismisses a toast by id", () => {
    const id = toast.info("Hi");
    toast.dismiss(id);
    expect(getToasts()).toHaveLength(0);
  });

  it("dismiss() with no id clears all toasts", () => {
    toast.info("a");
    toast.error("b");
    toast.dismiss();
    expect(getToasts()).toHaveLength(0);
  });

  it("caps at max, evicting the oldest (newest first)", () => {
    setMaxToasts(2);
    toast.info("1");
    toast.info("2");
    toast.info("3");
    expect(getToasts().map((t) => t.title)).toEqual(["3", "2"]);
  });

  it("updates in place when an explicit id is reused", () => {
    toast.loading("Working", { id: "x" });
    toast.success("Done", { id: "x" });
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ id: "x", variant: "success", title: "Done" });
  });

  it("applies per-variant default durations (error sticky, success 4s)", () => {
    const e = toast.error("boom");
    const s = toast.success("ok");
    const byId = (id: string) => getToasts().find((t) => t.id === id)!;
    expect(byId(e).duration).toBe(Number.POSITIVE_INFINITY);
    expect(byId(s).duration).toBe(4000);
  });

  it("honours an explicit duration override", () => {
    const id = toast.error("boom", { duration: 9000 });
    expect(getToasts().find((t) => t.id === id)!.duration).toBe(9000);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- src/lib/toast-store.test.ts`
Expected: FAIL — `Cannot find module './toast-store'`.

- [ ] **Step 3: Implement the store**

Create `web/src/lib/toast-store.ts`:

```ts
import { useSyncExternalStore } from "react";

export type ToastVariant = "info" | "success" | "error" | "loading";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastData {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  action?: ToastAction;
  duration: number; // ms; Number.POSITIVE_INFINITY = sticky
}

export interface ToastOptions {
  description?: string;
  action?: ToastAction;
  duration?: number;
  id?: string; // stable id => update existing toast in place
}

const DEFAULT_DURATION: Record<ToastVariant, number> = {
  info: 4000,
  success: 4000,
  error: Number.POSITIVE_INFINITY,
  loading: Number.POSITIVE_INFINITY,
};

let toasts: ToastData[] = [];
let maxToasts = 4;
let seq = 0;
const listeners = new Set<() => void>();

function notify() {
  for (const cb of listeners) cb();
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** Current snapshot — stable reference between mutations (for tests + the hook). */
export function getToasts(): ToastData[] {
  return toasts;
}

function upsert(data: ToastData) {
  const idx = toasts.findIndex((t) => t.id === data.id);
  if (idx >= 0) {
    const next = toasts.slice();
    next[idx] = data;
    toasts = next;
  } else {
    toasts = [data, ...toasts].slice(0, maxToasts);
  }
  notify();
}

function make(variant: ToastVariant, title: string, opts: ToastOptions = {}): string {
  const id = opts.id ?? `toast-${++seq}`;
  upsert({
    id,
    variant,
    title,
    description: opts.description,
    action: opts.action,
    duration: opts.duration ?? DEFAULT_DURATION[variant],
  });
  return id;
}

function update(id: string, patch: Partial<Omit<ToastData, "id">>) {
  const idx = toasts.findIndex((t) => t.id === id);
  if (idx < 0) return;
  const next = toasts.slice();
  next[idx] = { ...next[idx], ...patch };
  toasts = next;
  notify();
}

function dismiss(id?: string) {
  toasts = id ? toasts.filter((t) => t.id !== id) : [];
  notify();
}

type Msg<T> = string | ((value: T) => string);
function resolveMsg<T>(m: Msg<T>, v: T): string {
  return typeof m === "function" ? (m as (v: T) => string)(v) : m;
}

export const toast = {
  info: (title: string, opts?: ToastOptions) => make("info", title, opts),
  success: (title: string, opts?: ToastOptions) => make("success", title, opts),
  error: (title: string, opts?: ToastOptions) => make("error", title, opts),
  loading: (title: string, opts?: ToastOptions) => make("loading", title, opts),
  custom: (variant: ToastVariant, title: string, opts?: ToastOptions) => make(variant, title, opts),
  dismiss,
  promise<T>(p: Promise<T>, m: { loading: string; success: Msg<T>; error: Msg<unknown> }): string {
    const id = make("loading", m.loading);
    p.then(
      (v) =>
        update(id, {
          variant: "success",
          title: resolveMsg(m.success, v),
          duration: DEFAULT_DURATION.success,
        }),
      (e) =>
        update(id, {
          variant: "error",
          title: resolveMsg(m.error, e),
          duration: DEFAULT_DURATION.error,
        }),
    );
    return id;
  },
};

export function setMaxToasts(n: number) {
  maxToasts = n;
}

/** Test-only: reset module singleton state between tests. */
export function resetToastStore() {
  toasts = [];
  seq = 0;
  maxToasts = 4;
  notify();
}

export function useToasts(): ToastData[] {
  return useSyncExternalStore(subscribe, getToasts, getToasts);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/lib/toast-store.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/toast-store.ts web/src/lib/toast-store.test.ts
git commit -m "feat(web): toast store — imperative add/dismiss/cap/update"
```

---

## Task 2: Toast store — promise lifecycle

**Files:**
- Modify: `web/src/lib/toast-store.ts` (already implements `toast.promise` from Task 1 — this task only adds the tests proving it)
- Test: `web/src/lib/toast-store.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `web/src/lib/toast-store.test.ts`:

```ts
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("toast.promise", () => {
  it("starts as loading", () => {
    toast.promise(new Promise(() => {}), { loading: "Loading", success: "OK", error: "Err" });
    expect(getToasts()[0]).toMatchObject({ variant: "loading", title: "Loading" });
  });

  it("morphs the same toast loading -> success", async () => {
    toast.promise(Promise.resolve("v"), {
      loading: "Loading",
      success: (v) => `Got ${v}`,
      error: "Err",
    });
    await flush();
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "success", title: "Got v" });
  });

  it("morphs the same toast loading -> error on reject", async () => {
    toast.promise(Promise.reject(new Error("nope")), {
      loading: "L",
      success: "S",
      error: (e) => (e as Error).message,
    });
    await flush();
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "error", title: "nope" });
  });
});
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `npm test -- src/lib/toast-store.test.ts`
Expected: PASS (10 tests total). `toast.promise` was implemented in Task 1; these tests confirm the lifecycle. If any fail, fix `toast-store.ts` — do not change the tests.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/toast-store.test.ts
git commit -m "test(web): cover toast.promise lifecycle"
```

---

## Task 3: ui/toast.tsx — Radix wrappers + variant icon

**Files:**
- Create: `web/src/components/ui/toast.tsx`

This file is presentational (styled Radix wrappers, same pattern as `ui/alert-dialog.tsx`); it is exercised by the `Toaster` tests in Task 4, so it has no standalone unit test. Verification is a typecheck.

- [ ] **Step 1: Implement the wrappers**

Create `web/src/components/ui/toast.tsx`:

```tsx
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
      "max-sm:top-auto max-sm:bottom-0 max-sm:inset-x-0 max-sm:w-full max-sm:max-w-full max-sm:p-3",
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
      "bg-[#141417] border-[var(--border)] text-[var(--text)]",
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
```

- [ ] **Step 2: Verify it typechecks**

Run: `npx tsc -b`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ui/toast.tsx
git commit -m "feat(web): styled Radix toast primitives"
```

---

## Task 4: Toaster renderer + renderWithToaster helper

**Files:**
- Create: `web/src/components/toaster.tsx`
- Test: `web/src/components/toaster.test.tsx`
- Modify: `web/src/test-utils/render.tsx`

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/toaster.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "./toaster";
import { toast, resetToastStore } from "@/lib/toast-store";

beforeEach(() => resetToastStore());

describe("Toaster", () => {
  it("renders a toast pushed onto the store", async () => {
    render(<Toaster />);
    toast.success("Added to library");
    expect(await screen.findByText("Added to library")).toBeInTheDocument();
  });

  it("renders the description", async () => {
    render(<Toaster />);
    toast.success("Added to library", { description: "Tycho — Awake" });
    expect(await screen.findByText("Tycho — Awake")).toBeInTheDocument();
  });

  it("fires the action's onClick", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Toaster />);
    toast.success("Added", { action: { label: "Reveal", onClick } });
    await user.click(await screen.findByRole("button", { name: "Reveal" }));
    expect(onClick).toHaveBeenCalled();
  });

  it("dismisses via the close button", async () => {
    const user = userEvent.setup();
    render(<Toaster />);
    toast.info("Hello");
    await screen.findByText("Hello");
    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    await waitFor(() => expect(screen.queryByText("Hello")).not.toBeInTheDocument());
  });

  it("renders no close button on a loading toast (sticky)", async () => {
    render(<Toaster />);
    toast.loading("Queueing 3 downloads…");
    await screen.findByText("Queueing 3 downloads…");
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- src/components/toaster.test.tsx`
Expected: FAIL — `Cannot find module './toaster'`.

- [ ] **Step 3: Implement the Toaster**

Create `web/src/components/toaster.tsx`:

```tsx
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
```

Notes: sticky toasts (`error`/`loading`) carry `duration = Infinity` in the store; the Toaster maps any non-finite duration to ~24h so Radix's auto-close timer never fires — independent of how Radix handles `Infinity`. v1 removes a toast from the store on dismiss (enter animation only); exit-animation polish is deferred.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/components/toaster.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the `renderWithToaster` test helper**

In `web/src/test-utils/render.tsx`, add the import at the top (after the existing imports):

```tsx
import { Toaster } from "@/components/toaster";
```

and add this export at the end of the file:

```tsx
export function renderWithToaster(ui: ReactElement, options?: RenderOptions) {
  return renderUI(
    <>
      {ui}
      <Toaster />
    </>,
    options,
  );
}
```

- [ ] **Step 6: Verify the helper typechecks**

Run: `npx tsc -b`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/toaster.tsx web/src/components/toaster.test.tsx web/src/test-utils/render.tsx
git commit -m "feat(web): Toaster renderer + renderWithToaster test helper"
```

---

## Task 5: Mount the Toaster app-wide

**Files:**
- Modify: `web/src/routes/__root.tsx`

- [ ] **Step 1: Mount `<Toaster />` in the shell**

In `web/src/routes/__root.tsx`, add the import:

```tsx
import { Toaster } from "@/components/toaster";
```

and render it inside the shell `<div>`, after `</main>`:

```tsx
      <main>
        <Outlet />
      </main>
      <Toaster />
    </div>
```

- [ ] **Step 2: Verify build + full suite still green**

Run: `npx tsc -b && npm test`
Expected: PASS (all existing tests + the new toast tests).

- [ ] **Step 3: Commit**

```bash
git add web/src/routes/__root.tsx
git commit -m "feat(web): mount Toaster in app shell"
```

---

## Task 6: Surface errors in url-input

**Files:**
- Modify: `web/src/components/url-input.tsx`
- Test: `web/src/components/url-input.test.tsx`

- [ ] **Step 1: Write the failing test**

First add these imports at the top of `web/src/components/url-input.test.tsx` (alongside the existing imports — `server`, `http`, `HttpResponse`, `userEvent`, `UrlInput`, and `beforeEach` are already imported):

```tsx
import { screen } from "@testing-library/react";
import { resetToastStore } from "@/lib/toast-store";
import { renderWithToaster } from "@/test-utils/render";
```

Then append this block to the end of the file:

```tsx
describe("UrlInput toasts", () => {
  beforeEach(() => resetToastStore());

  it("shows an error toast when the job request fails", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ detail: "no" }, { status: 500 })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput onJobCreated={() => {}} />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/couldn't queue/i)).toBeInTheDocument();
  });

  it("shows a success toast after queueing", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "j", urls: [{ url: "https://x.test/a", format: "m4a" }] })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput onJobCreated={() => {}} />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/queued 1 download/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/components/url-input.test.tsx`
Expected: FAIL — no toast text found (handler still swallows errors).

- [ ] **Step 3: Wire `toast.promise` into the submit handler**

In `web/src/components/url-input.tsx`, add the import:

```tsx
import { toast } from "@/lib/toast-store";
```

and replace the entire `handleAdd` function (it spans roughly lines 16-33) with:

```tsx
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
      success: (r) => `Queued ${r.urls.length} download${r.urls.length === 1 ? "" : "s"}`,
      error: "Couldn't queue download",
    });
    try {
      const r = await req;
      onJobCreated(r.job_id);
      setValue("");
    } catch {
      /* surfaced by the toast above */
    } finally {
      setSubmitting(false);
    }
  }
```

Note: `postJobs(urls)` is called once (`req`) and shared between `toast.promise` and the `await` — no double request.

- [ ] **Step 4: Run to verify the new tests pass and the old ones still pass**

Run: `npm test -- src/components/url-input.test.tsx`
Expected: PASS (3 original + 2 new = 5 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/url-input.tsx web/src/components/url-input.test.tsx
git commit -m "feat(web): surface job-queue errors via toast in url-input"
```

---

## Task 7: Surface errors in library-tile-menu

**Files:**
- Modify: `web/src/components/library-tile-menu.tsx`
- Test: `web/src/components/library-tile-menu.test.tsx`

- [ ] **Step 1: Write the failing tests**

At the top of `web/src/components/library-tile-menu.test.tsx`, add `beforeEach` to the existing `from "vitest"` import, and add these import lines:

```tsx
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test-utils/server";
import { resetToastStore } from "@/lib/toast-store";
import { renderWithToaster } from "@/test-utils/render";
```

Then append this block to the end of the file:

```tsx
describe("LibraryTileMenu toasts", () => {
  beforeEach(() => resetToastStore());

  it("shows a success toast after starting a re-download", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "j", urls: [] })));
    const user = userEvent.setup();
    renderWithToaster(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <button>tile</button>
      </LibraryTileMenu>,
    );
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("tile") });
    await user.click(await screen.findByText(/re-download/i));
    expect(await screen.findByText(/re-downloading/i)).toBeInTheDocument();
  });

  it("shows an error toast when reveal fails", async () => {
    server.use(http.post("/reveal", () => HttpResponse.json({}, { status: 500 })));
    const user = userEvent.setup();
    renderWithToaster(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <button>tile</button>
      </LibraryTileMenu>,
    );
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("tile") });
    await user.click(await screen.findByText(/reveal in finder/i));
    expect(await screen.findByText(/couldn't reveal/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/components/library-tile-menu.test.tsx`
Expected: FAIL — toast text not found.

- [ ] **Step 3: Add toasts to the menu actions**

In `web/src/components/library-tile-menu.tsx`, add the import:

```tsx
import { toast } from "@/lib/toast-store";
```

and replace the two handler functions (`handleReveal`, `handleReDownload`) with:

```tsx
  async function handleReveal() {
    if (!item.paths[0]) return;
    try {
      await reveal(item.paths[0]);
    } catch {
      toast.error("Couldn't reveal file");
    }
  }
  async function handleReDownload() {
    try {
      await postJobs([{ url: item.url, format: item.media_format }]);
      toast.success("Re-downloading…", { description: item.title ?? item.url });
    } catch {
      toast.error("Couldn't start re-download");
    }
  }
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/components/library-tile-menu.test.tsx`
Expected: PASS (2 original + 2 new = 4 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/library-tile-menu.tsx web/src/components/library-tile-menu.test.tsx
git commit -m "feat(web): surface reveal/re-download errors via toast"
```

---

## Task 8: Download lifecycle toasts in job-tracker

**Files:**
- Modify: `web/src/components/job-tracker.tsx`
- Test: `web/src/components/job-tracker.test.tsx` (new)

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/job-tracker.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { renderWithToaster } from "@/test-utils/render";
import { resetToastStore } from "@/lib/toast-store";
import { JobTracker } from "./job-tracker";
import type { JobSnapshot } from "@/lib/types";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  resetToastStore();
  localStorage.clear();
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;
});
afterEach(() => {
  delete (globalThis as unknown as { EventSource?: typeof MockEventSource }).EventSource;
});

function completed(): JobSnapshot {
  return {
    job_id: "job-1",
    state: "completed",
    started_at: 1,
    urls: [
      {
        url: "https://a",
        media_format: "m4a",
        state: "completed",
        progress_percent: 100,
        speed: null,
        eta: null,
        paths: ["/tmp/a.m4a"],
        error: null,
        thumb_id: null,
        title: "Awake",
        uploader: "Tycho",
      },
    ],
  };
}

function failed(): JobSnapshot {
  return {
    job_id: "job-2",
    state: "failed",
    started_at: 1,
    urls: [
      {
        url: "https://b",
        media_format: "m4a",
        state: "failed",
        progress_percent: 0,
        speed: null,
        eta: null,
        paths: [],
        error: "HTTP Error 403: Forbidden",
        thumb_id: null,
        title: "Kerala",
        uploader: "Bonobo",
      },
    ],
  };
}

describe("JobTracker toasts", () => {
  it("fires a success toast with the track title when a job completes", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], completed());
    });
    expect(await screen.findByText(/added to library/i)).toBeInTheDocument();
    expect(screen.getByText("Awake")).toBeInTheDocument();
  });

  it("fires an error toast with the error message when a job fails", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-2" />);
    act(() => {
      queryClient.setQueryData(["job", "job-2"], failed());
    });
    expect(await screen.findByText(/download failed/i)).toBeInTheDocument();
    expect(screen.getByText(/forbidden/i)).toBeInTheDocument();
  });

  it("fires the toast only once even if the snapshot object changes again", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], completed());
    });
    await screen.findByText(/added to library/i);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], { ...completed() });
    });
    await waitFor(() => expect(screen.getAllByText(/added to library/i)).toHaveLength(1));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/components/job-tracker.test.tsx`
Expected: FAIL — no toast text (JobTracker doesn't toast yet).

- [ ] **Step 3: Add lifecycle toasts with a once-guard**

Replace the whole body of `web/src/components/job-tracker.tsx` with:

```tsx
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useJobEvents } from "@/hooks/use-job-events";
import { useHistory } from "@/hooks/use-history";
import { reveal, postJobs } from "@/lib/api";
import { toast } from "@/lib/toast-store";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function JobTracker({ jobId }: { jobId: string }) {
  useJobEvents(jobId);
  const queryClient = useQueryClient();
  const { data } = useQuery<JobSnapshot>({ queryKey: ["job", jobId], enabled: false });
  const { addItem } = useHistory();
  const toastedRef = useRef(false);

  useEffect(() => {
    if (!data) return;
    if (!TERMINAL.includes(data.state)) return;
    if (toastedRef.current) return;
    toastedRef.current = true;

    for (const u of data.urls) {
      if (u.state === "completed") {
        addItem({
          url: u.url,
          title: u.title,
          artist: u.uploader,
          media_format: u.media_format,
          paths: u.paths,
          thumb_id: u.thumb_id,
          added_at: Date.now(),
        });
        toast.success("Added to library", {
          description: u.title ?? u.url,
          action: u.paths[0]
            ? {
                label: "Reveal",
                onClick: () => {
                  reveal(u.paths[0]).catch(() => toast.error("Couldn't reveal file"));
                },
              }
            : undefined,
        });
      } else if (u.state === "failed") {
        toast.error("Download failed", {
          description: u.error ?? u.title ?? u.url,
          action: {
            label: "Retry",
            onClick: () => {
              postJobs([{ url: u.url, format: u.media_format }]).catch(() =>
                toast.error("Couldn't start re-download"),
              );
            },
          },
        });
      }
    }

    setTimeout(() => queryClient.removeQueries({ queryKey: ["job", jobId] }), 1500);
  }, [data, addItem, jobId, queryClient]);

  return null;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/components/job-tracker.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/job-tracker.tsx web/src/components/job-tracker.test.tsx
git commit -m "feat(web): toast on download completion/failure with Reveal/Retry"
```

---

## Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `npm test`
Expected: PASS — all suites green, including the new `toast-store`, `toaster`, `job-tracker`, and extended `url-input` / `library-tile-menu` tests.

- [ ] **Step 2: Typecheck + production build**

Run: `npm run build`
Expected: PASS (`tsc -b` then `vite build`, no errors).

- [ ] **Step 3: Lint**

Run: `npm run lint`
Expected: PASS (Biome clean). If Biome reports formatting, run `npm run format` and re-commit.

- [ ] **Step 4: Manual smoke test (optional but recommended)**

Start the backend (`audio-dl-ui` from the repo root) and the Vite dev server (`npm run dev` from `web/`). Verify: pasting a bad URL shows an error toast; a good URL shows "Queueing…" → completion shows "Added to library" with a working Reveal; right-clicking a library tile → Reveal on a missing file shows an error toast.

- [ ] **Step 5: Final commit (only if lint/format changed files)**

```bash
git add -p   # stage only formatting changes
git commit -m "style(web): biome format toast files"
```

---

## Spec coverage check

- Reusable `ui/toast.tsx` (Radix wrappers + variants) → Task 3.
- Imperative `toast.*` store mirroring `use-history` → Tasks 1-2.
- Promise-morph toasts → Task 2 + Task 6 (url-input).
- `<Toaster>` + mount → Tasks 4-5.
- Semantic tokens + animations + reduced-motion → Task 0.
- Variant durations / live-region `type` (foreground vs background) → Task 1 (durations) + Task 4 (`type` mapping).
- Integration: url-input, library-tile-menu, job-tracker (with Reveal/Retry actions + once-guard) → Tasks 6-8.
- Responsive viewport + matchMedia swipe direction → Tasks 3-4.
- Scoping decision (route-bound lifecycle toasts) honored — toasts fire from `JobTracker` only; no app-wide tracking added.
- Tests in the Vitest + TL + MSW style → every task.
