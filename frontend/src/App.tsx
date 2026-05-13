import { REFRESH_STATUS_MS, REFRESH_TODAY_MS, useApi } from "@/hooks/useApi";

// Phase B scaffold — verifies the Vite + types + SWR wiring end-to-end by
// showing the raw JSON for the today-picks and system-status endpoints.
// Phase C replaces this with the real page components and routing.
function App() {
  const picks = useApi("/api/dashboard/today-picks", {
    refreshInterval: REFRESH_TODAY_MS,
  });
  const status = useApi("/api/dashboard/system-status", {
    refreshInterval: REFRESH_STATUS_MS,
  });

  return (
    <main className="mx-auto max-w-5xl p-6 space-y-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">
          AFL Predict <span className="text-muted">· dashboard</span>
        </h1>
        <span className="text-xs text-muted">
          phase B scaffold · replace in phase C
        </span>
      </header>

      <section className="card">
        <h2 className="card-title">today-picks</h2>
        {picks.isLoading && <p className="text-muted text-sm">loading…</p>}
        {picks.error && (
          <p className="text-loss text-sm">error: {String(picks.error)}</p>
        )}
        {picks.data && (
          <pre className="mt-2 max-h-80 overflow-auto text-xs text-muted">
            {JSON.stringify(picks.data, null, 2)}
          </pre>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">system-status</h2>
        {status.isLoading && <p className="text-muted text-sm">loading…</p>}
        {status.error && (
          <p className="text-loss text-sm">error: {String(status.error)}</p>
        )}
        {status.data && (
          <pre className="mt-2 max-h-80 overflow-auto text-xs text-muted">
            {JSON.stringify(status.data, null, 2)}
          </pre>
        )}
      </section>
    </main>
  );
}

export default App;
