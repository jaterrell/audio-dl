# Spec — Toast notifications (reusable feedback layer)

**Status:** Draft — pending review 2026-06-09
**Target files:** `web/` React app. New: `src/lib/toast-store.ts`,
`src/components/ui/toast.tsx`, `src/components/toaster.tsx`. Edited:
`src/routes/__root.tsx`, `src/styles/tokens.css`, `src/styles/globals.css`,
`src/components/url-input.tsx`, `src/components/library-tile-menu.tsx`,
`src/components/job-tracker.tsx`, `package.json`.
**Predecessor:** v2.0 web UI React rewrite
([2026-06-03-web-ui-v2-react-rewrite-design.md](2026-06-03-web-ui-v2-react-rewrite-design.md))
**Follow-ups deferred:** mini-player download bar; settings panel; app-wide
(cross-route) download-lifecycle toasts.

## Goal

Add a **reusable, accessible toast/notification layer** to the web UI and wire
it into the places the app currently fails silently.

Today failures are invisible:

- `postJobs` errors are swallowed by `console.error` in
  [url-input.tsx:29](../../../web/src/components/url-input.tsx) and both actions
  in [library-tile-menu.tsx](../../../web/src/components/library-tile-menu.tsx).
- A download that **fails** (`url_failed`) records its error in `UrlState`, but
  the Now screen only renders *running* and *queued* jobs
  ([index.tsx:19-23](../../../web/src/routes/index.tsx)), so a failed job
  silently disappears — the user never learns it failed or why.

The deliverable is a small, well-bounded component family — a Radix-backed
`ui/toast.tsx`, an imperative `toast.*` store, and a `<Toaster>` renderer — plus
the integrations that make failures (and successes) visible.

## Non-goals

- **Cross-route lifecycle toasts** — a toast when a download finishes while the
  user is on a different route (see [Scoping decision](#scoping-decision--route-bound-lifecycle-toasts)).
- A notification center / persisted history of past toasts.
- **Backend changes** — none. Retry re-uses `POST /jobs`; Reveal re-uses
  `POST /reveal`.
- Stack "expand/collapse" UX beyond a simple newest-N cap.
- Light mode (app is dark-only).

## Approach

Radix `@radix-ui/react-toast` wrapped in `ui/toast.tsx`, exactly mirroring the
existing `ui/alert-dialog.tsx` pattern (export the primitive `Root`/`Provider`,
`forwardRef` styled parts, `cn`, `cva` variants). Radix supplies the
accessibility and interaction model we would otherwise re-implement: an ARIA
live region, the F8 focus hotkey, swipe-to-dismiss, pause-on-hover/focus, and
per-toast timers. We own the visual design, the imperative API, and the
promise/loading lifecycle.

Rejected alternatives: **sonner** (black-box dep, thin "design a component"
surface, fights the token theme) and **from-scratch** (re-implements solved a11y
for no benefit, since Radix is already the house style — 7 `@radix-ui/*` deps
ship today).

## Component architecture

| File | Role |
|---|---|
| `src/lib/toast-store.ts` *(+ test)* | Module-level store + imperative `toast.*` API + `useToasts()`. Mirrors the `use-history.ts` / `use-settings.ts` store pattern (module state + `subscribe` + `useSyncExternalStore` + lazy cached snapshot). Importable from non-React code (e.g. the SSE layer). |
| `src/components/ui/toast.tsx` | Styled Radix wrappers: `ToastProvider`, `ToastViewport`, `Toast` (cva variants), `ToastTitle`, `ToastDescription`, `ToastAction`, `ToastClose`. Same `forwardRef` + `cn` pattern as `ui/alert-dialog.tsx`. |
| `src/components/toaster.tsx` *(+ test)* | `<Toaster>` — subscribes via `useToasts()`, renders one `ToastProvider` + `ToastViewport` and maps store entries to `<Toast>`s. Mounted once. |
| `src/routes/__root.tsx` | Mount `<Toaster />` in `AppShell` (app-wide). |
| `src/styles/tokens.css` | Add semantic color tokens (`--ok/--err/--warn/--info` + `-bg` tints). |
| `src/styles/globals.css` | Toast keyframes keyed off Radix `data-state` / `data-swipe`, gated by `prefers-reduced-motion`. |
| `package.json` | `+ @radix-ui/react-toast` |
| `url-input.tsx`, `library-tile-menu.tsx`, `job-tracker.tsx` | Integration (replace `console.error`; add lifecycle toasts). |

## Public API (props design)

```ts
// imperative — callable from anywhere, no hook/context required
toast.info(title, opts?)      // -> id
toast.success(title, opts?)   // -> id
toast.error(title, opts?)     // -> id
toast.loading(title, opts?)   // -> id
toast.promise(p, { loading, success, error })  // -> id
toast.dismiss(id?)            // dismiss one, or all if omitted

interface ToastOptions {
  description?: string
  action?: { label: string; onClick: () => void }
  duration?: number   // ms; Infinity = sticky. Defaults per-variant (see below).
  id?: string         // stable id => updates the existing toast in place (dedupe)
}

// promise messages — success/error may read the resolved value / error
type Msg<T> = string | ((value: T) => string)
toast.promise<T>(p: Promise<T>, m: { loading: string; success: Msg<T>; error: Msg<unknown> })

// renderer
<Toaster max={4} />   // max defaults to 4
```

`ui/toast.tsx` exports the composable Radix-wrapped primitives (mirrors how
`alert-dialog.tsx` exports its parts), so `<Toaster>` — or any future caller —
composes them rather than re-styling Radix.

## Store contract (`lib/toast-store.ts`)

```ts
type ToastVariant = "info" | "success" | "error" | "loading"

interface ToastData {
  id: string
  variant: ToastVariant
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
  duration: number      // resolved (variant default unless overridden)
}
```

- Module-level `let toasts: ToastData[]`, `Set<() => void>` listeners,
  `subscribe`/`notify`, lazy cached snapshot — identical shape to
  `use-history.ts`. `useToasts()` returns the array via `useSyncExternalStore`.
- Ids come from a module counter (`toast-1`, `toast-2`, …) so test output is
  deterministic; `opts.id` overrides for dedupe/update.
- `add(partial)` prepends, then **caps to `max` (default 4), evicting the
  oldest** — sticky toasts (error/loading) count toward the cap.
- `update(id, patch)` mutates the matching entry in place (keeps id + position).
- `toast.promise` = `add({variant:"loading", duration:Infinity})`, then on
  settle `update(id, {variant:"success"|"error", title, duration})`. The toast
  **morphs in place** (same id/key) rather than stacking a second toast.

`<Toaster max>` configures the store cap on mount.

## Variants & behavior

| Variant | Icon (lucide) | Color token | Live-region `type` | Default duration |
|---|---|---|---|---|
| `info` | `Info` | `--info` | `background` (polite) | 4000 ms |
| `success` | `CheckCircle2` | `--ok` | `background` (polite) | 4000 ms |
| `error` | `XCircle` | `--err` | `foreground` (assertive) | `Infinity` (sticky) |
| `loading` | `Loader2` (spin) | `--text-2` | `background` (polite) | `Infinity` (until settle) |

Per-toast `duration` (incl. `Infinity`) is passed straight to the Radix `Toast`
`duration` prop — Radix owns the timer, pause-on-hover/focus, and swipe.

## Data flow

- **Imperative:** call site → `toast.error()` → store mutates + notifies →
  `<Toaster>` re-renders → Radix portals into the viewport → live region
  announces.
- **Promise:** `toast.promise()` adds a `loading` toast (returns its id); on
  settle it patches that same toast to `success`/`error`, which resets the Radix
  timer (was `Infinity`, now finite) and auto-dismisses.

## States & edge cases

- **Loading → resolved:** promise toasts morph from spinner to success/error in
  place.
- **Batch failure** (paste 20 bad URLs): cap of 4 visible, oldest evicted;
  callers that should not stack pass a stable `id`.
- **Long text:** `title` single line (`truncate`); `description`
  `line-clamp-3`, full text in the element `title` attribute.
- **Reduced motion:** all toast animations disabled under
  `prefers-reduced-motion: reduce`.
- **Fired outside React** (SSE/data layer): works — the store is module-level
  and `toast.*` needs no hook/context.
- **jsdom/tests:** renders; assert `role="status"` (polite) / `role="alert"`
  (assertive, error).

## Accessibility

- Radix `ToastProvider` owns the visually-hidden live region; `type`
  (`foreground`/`background`) maps to `assertive`/`polite` per the variant table.
- F8 hotkey jumps focus to the toast region (Radix default); toasts are
  reachable and dismissable by keyboard.
- Close button has `aria-label="Dismiss"`; action button uses its visible label.
- Toasts never steal focus on appear (Radix default) — they announce, they don't
  interrupt.

## Responsive

- Viewport: `fixed top-4 right-4 w-[380px] max-w-[calc(100vw-2rem)]` on desktop;
  on `max-sm` it docks full-width to the bottom
  (`bottom-0 inset-x-0 top-auto w-full`).
- `ToastProvider swipeDirection` is `"right"` on `≥640px` and `"down"` below,
  chosen via a small `matchMedia` hook so swipe-to-dismiss matches the dock edge.

## Animations (`globals.css`)

Keyframes keyed off Radix attributes on the `Toast` root
(`data-state="open"|"closed"`, `data-swipe="move"|"cancel"|"end"`,
`--radix-toast-swipe-move-x/y`): slide+fade in, slide+fade out, follow-finger on
swipe. Desktop animates on X, mobile dock on Y. All wrapped in
`@media (prefers-reduced-motion: reduce) { … animation: none }`. First animated
component in the app — no `tailwindcss-animate` dependency; hand-written
keyframes (consistent with the Tailwind v4 setup).

## New design tokens (`tokens.css`)

The app has **no** semantic status colors, and `--accent` is overwritten at
runtime by `useVibrant` (album color), so it cannot carry meaning. Add:

```css
--ok:   #34d399;  --ok-bg:   rgb(52 211 153 / 0.14);
--err:  #f87171;  --err-bg:  rgb(248 113 113 / 0.14);
--warn: #fbbf24;  --warn-bg: rgb(251 191 36 / 0.14);
--info: #60a5fa;  --info-bg: rgb(96 165 250 / 0.14);
```

The `cva` variants in `ui/toast.tsx` map icon color → `--{ok,err,info}` and the
icon chip background → `--{ok,err,info}-bg`. The `loading` variant is neutral —
chip background `--surface-strong`, icon in `--text-2`. (`--warn` is added for
completeness; no v1 variant uses it yet.)

## Integration points — where silent failures get fixed

- **`url-input.tsx`:** wrap `postJobs` in `toast.promise` —
  `"Queueing N download(s)…"` → `"Queued N download(s)"` / error. Removes the
  `console.error`.
- **`library-tile-menu.tsx`:** `reveal` and `re-download` failures →
  `toast.error`; successful re-download → `toast.success("Re-downloading…")`.
  Removes both `console.error`s.
- **`job-tracker.tsx`:** in the existing terminal-state effect (which already
  adds completed URLs to history), also fire, **once per job** (guarded by a
  `useRef`):
  - completed URL → `toast.success("Added to library", { description: title, action: { label: "Reveal", onClick: () => reveal(paths[0]) } })`
  - failed URL → `toast.error("Download failed", { description: error ?? title, action: { label: "Retry", onClick: () => postJobs([{ url, format: media_format }]) } })`

## Scoping decision — route-bound lifecycle toasts

`JobTracker` (which fires the completed/failed toasts) only mounts on the **Now**
route, via `trackedJobs` state in `NowScreen`
([index.tsx:27](../../../web/src/routes/index.tsx)); leaving the route unmounts
it and the SSE subscription already freezes. So lifecycle toasts cover the
primary flow (paste a URL, watch it finish) but **will not fire if a download
completes while the user is on the Library route**.

Making lifecycle events truly app-wide requires lifting job tracking into
`__root.tsx` (an `AppShell`-level tracker) — which is the **mini-player bar's**
job (deferred follow-up). Doing it here would duplicate that work and pull this
PR's scope wider than the component itself. *Imperative* error toasts (from any
user action) work on every route regardless; only the passive completed/failed
toasts are route-bound. This is a deliberate v1 limitation, not an oversight.

## Dependencies

`@radix-ui/react-toast` (`^1.2.x`, React 19 compatible) added to `web/`
`dependencies` — consistent with the 7 `@radix-ui/*` packages already present.
No backend or build-config changes.

## Testing (Vitest + Testing Library + MSW)

- `toast-store.test.ts` — add/dismiss; `promise` resolve and reject lifecycle;
  `max` cap evicts oldest; stable-`id` updates in place; `dismiss()` clears all.
- `toaster.test.tsx` — renders a toast by role; `success`→`role="status"`,
  `error`→`role="alert"`; action button fires its `onClick`; close button
  dismisses.
- Integration — MSW 500 on `POST /jobs` ⇒ `url-input` shows an error toast;
  `library-tile-menu` reveal failure ⇒ error toast; `JobTracker` drives a
  terminal `success`/`error` toast (via seeded query-cache snapshot).

Tests render with the shared `renderUI` helper; component/integration tests
mount `<Toaster>` alongside the unit under test (a `renderWithToaster` helper in
`test-utils`).

## Open questions

None blocking. One judgment call to confirm at review: **error toasts are sticky
(`duration: Infinity`)** by default so they can be read and retried — dismiss via
swipe, the close button, or F8→Esc. If you'd rather they auto-dismiss on a long
timer (e.g. 10 s), that's a one-line default change.
