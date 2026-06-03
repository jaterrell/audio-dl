import { createRootRoute, Outlet, Link } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: AppShell,
});

function AppShell() {
  return (
    <div className="min-h-screen">
      <header className="flex justify-between items-center px-7 py-5">
        <div className="flex items-center gap-3 font-semibold">audio-dl</div>
        <nav className="flex gap-1">
          <Link
            to="/"
            className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
            activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
          >
            Now
          </Link>
          <Link
            to="/library"
            className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
            activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
          >
            Library
          </Link>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
