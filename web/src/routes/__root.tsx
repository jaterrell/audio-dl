import { createRootRoute, Outlet, Link, useRouterState } from "@tanstack/react-router";
import { Toaster } from "@/components/toaster";
import { ThemeToggle } from "@/components/theme-toggle";
import { useTheme } from "@/hooks/use-theme";

export const Route = createRootRoute({
  component: AppShell,
});

function AppShell() {
  useTheme();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <div className="min-h-screen">
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
