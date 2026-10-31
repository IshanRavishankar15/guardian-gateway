"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type RouteInfo = {
  id: string; name: string; path_prefix: string; upstream_base_url: string;
  methods: string[]; enabled: boolean; timeout_seconds: number;
};
type PolicyInfo = {
  id: string; name: string; client_id: string | null; route_id: string | null;
  capacity: number; refill_rate: number; enabled: boolean;
};
type MetricsSummary = {
  requests_total: number; rate_limit_rejections_total: number; upstream_errors_total: number;
  upstream_timeouts_total: number; average_latency_seconds: number; p95_latency_seconds: number;
};

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function getAdminData<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { headers: { "X-Admin-Token": token }, cache: "no-store" });
  if (!response.ok) {
    let message = `Backend returned HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? body.error?.message ?? message;
    } catch {
      // Keep the status message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function formatLatency(seconds: number): string {
  return seconds < 0.001 ? `${(seconds * 1000).toFixed(2)} ms` : `${(seconds * 1000).toFixed(1)} ms`;
}

export default function Home() {
  const [adminToken, setAdminToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [routes, setRoutes] = useState<RouteInfo[]>([]);
  const [policies, setPolicies] = useState<PolicyInfo[]>([]);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    if (!adminToken) return;
    setLoading(true);
    setError("");
    try {
      const [routeData, policyData, summary] = await Promise.all([
        getAdminData<RouteInfo[]>("/admin/routes", adminToken),
        getAdminData<PolicyInfo[]>("/admin/rate-limit-policies", adminToken),
        getAdminData<MetricsSummary>("/admin/metrics/summary", adminToken),
      ]);
      setRoutes(routeData);
      setPolicies(policyData);
      setMetrics(summary);
      setConnected(true);
      setLastUpdated(new Date());
    } catch (loadError) {
      setConnected(false);
      setError(loadError instanceof Error ? loadError.message : "Unable to load gateway data");
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => {
    if (!connected) return;
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [connected, refresh]);

  const routeNames = useMemo(() => new Map(routes.map((route) => [route.id, route.name])), [routes]);

  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConnected(false);
    void refresh();
  }

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Guardian Gateway home"><span className="brand-mark">G</span><span>GUARDIAN <strong>GATEWAY</strong></span></a>
        <div className="topbar-right">
          <span className={`status-pill ${connected ? "is-online" : "is-offline"}`}><span className="status-dot" />{connected ? "CONNECTED" : "DISCONNECTED"}</span>
          {connected && <button className="refresh-button" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>}
        </div>
      </header>

      <section className="intro">
        <div><p className="eyebrow">CONTROL PLANE / OVERVIEW</p><h1>Gateway overview</h1><p className="intro-copy">A live view of your routes, traffic, and rate-limit policies.</p></div>
        <form className="connect-form" onSubmit={connect}>
          <label htmlFor="admin-token">Admin token</label>
          <div className="token-row"><input id="admin-token" type="password" autoComplete="current-password" value={adminToken} onChange={(event) => setAdminToken(event.target.value)} placeholder="Enter admin token" required /><button type="submit" disabled={loading || !adminToken}>{loading ? "Loading…" : "Connect"}</button></div>
          <span className="field-note">Used in this tab only; not saved to browser storage.</span>
        </form>
      </section>

      {error && <div className="error-banner" role="alert"><strong>Could not load dashboard data.</strong> {error}</div>}

      <section className="metric-grid" aria-label="Traffic summary">
        <article className="metric-card primary-card"><div className="card-label"><span className="card-icon icon-blue">↗</span><span>Requests handled</span></div><strong className="metric-value">{metrics?.requests_total.toLocaleString() ?? "—"}</strong><span className="metric-caption">Since this gateway process started</span></article>
        <article className="metric-card"><div className="card-label"><span className="card-icon icon-amber">⊘</span><span>Rate-limit rejections</span></div><strong className="metric-value">{metrics?.rate_limit_rejections_total.toLocaleString() ?? "—"}</strong><span className="metric-caption">Requests denied by policy</span></article>
        <article className="metric-card"><div className="card-label"><span className="card-icon icon-red">!</span><span>Upstream errors</span></div><strong className="metric-value">{metrics?.upstream_errors_total.toLocaleString() ?? "—"}</strong><span className="metric-caption">{metrics?.upstream_timeouts_total.toLocaleString() ?? "—"} timeouts</span></article>
        <article className="metric-card"><div className="card-label"><span className="card-icon icon-green">◷</span><span>Request latency</span></div><strong className="metric-value">{metrics ? formatLatency(metrics.average_latency_seconds) : "—"}</strong><span className="metric-caption">P95 {metrics ? formatLatency(metrics.p95_latency_seconds) : "—"}</span></article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">TRAFFIC CONTROL</p><h2>Configured routes</h2></div><span className="count-badge">{connected ? routes.length : "—"}</span></div>
          {!connected ? <div className="empty-state">Connect with an admin token to load routes.</div> : routes.length === 0 ? <div className="empty-state">No routes configured yet.</div> : (
            <div className="route-list">{routes.map((route) => <div className="route-row" key={route.id}>
              <div className="route-symbol">⇢</div><div className="route-details"><div className="route-title"><strong>{route.name}</strong><span className={`enabled-tag ${route.enabled ? "enabled" : "disabled"}`}>{route.enabled ? "Enabled" : "Disabled"}</span></div><code>{route.path_prefix}</code><span className="upstream-url">{route.upstream_base_url}</span></div>
              <div className="route-meta"><span>{route.methods.join(" · ")}</span><span>{route.timeout_seconds}s timeout</span></div>
            </div>)}</div>
          )}
        </article>

        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">QUOTA CONFIGURATION</p><h2>Rate-limit policies</h2></div><span className="count-badge">{connected ? policies.length : "—"}</span></div>
          {!connected ? <div className="empty-state">Connect with an admin token to load policies.</div> : policies.length === 0 ? <div className="empty-state">No rate-limit policies configured.</div> : (
            <div className="policy-list">{policies.map((policy) => {
              const scope = policy.client_id && policy.route_id ? `${policy.client_id.slice(0, 8)} · ${routeNames.get(policy.route_id) ?? "route"}` : policy.client_id ? `Client ${policy.client_id.slice(0, 8)}` : policy.route_id ? routeNames.get(policy.route_id) ?? `Route ${policy.route_id.slice(0, 8)}` : "Global";
              return <div className="policy-row" key={policy.id}><div className="policy-topline"><strong>{policy.name}</strong><span className={`enabled-tag ${policy.enabled ? "enabled" : "disabled"}`}>{policy.enabled ? "Active" : "Disabled"}</span></div><div className="policy-details"><span>{scope}</span><span><b>{policy.capacity}</b> burst</span><span><b>{policy.refill_rate}</b> tokens/s</span></div></div>;
            })}</div>
          )}
        </article>
      </section>

      <footer className="footer"><span>Guardian Gateway <span className="footer-separator">·</span> Prometheus metrics</span><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : "Waiting for connection"}</span></footer>
    </main>
  );
}
