import { createRootRoute, Outlet, Link, useRouterState } from "@tanstack/react-router";
import { Toaster } from "@/components/toaster";
import { ThemeToggle } from "@/components/theme-toggle";
import { JobTracker } from "@/components/job-tracker";
import { useTheme } from "@/hooks/use-theme";
import { usePresence } from "@/hooks/use-presence";
import { useTrackedJobs, trackJob } from "@/lib/tracked-jobs";

export const Route = createRootRoute({
  component: AppShell,
});

function AppShell() {
  useTheme();
  // Tells the backend a window is open; when all windows close, the backend
  // auto-exits instead of lingering in the background.
  usePresence();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const tracked = useTrackedJobs();
  return (
    <div className="min-h-screen">
      {/* Mounted app-wide (not per route) so SSE tracking + completion toasts
          survive navigation. JobTracker renders nothing. */}
      {tracked.map((id) => (
        <JobTracker key={id} jobId={id} onJobCreated={trackJob} />
      ))}
      <header className="flex justify-between items-center gap-3 px-4 sm:px-7 py-4 sm:py-5">
        <div className="flex items-center gap-3 font-semibold shrink-0">audio-dl</div>
        <div className="flex items-center gap-2 sm:gap-4">
          <nav className="flex gap-1">
            <Link
              to="/"
              className="focus-ring px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
              activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
            >
              Now
            </Link>
            <Link
              to="/library"
              className="focus-ring px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
              activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
            >
              Library
            </Link>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main>
        <div key={pathname} className="enter-fade">
          <Outlet />
        </div>
      </main>
      <Toaster />
    </div>
  );
}
