import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export function DashboardPage() {
  const [stats, setStats] = useState<Awaited<ReturnType<typeof api.dashboard>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.dashboard().then(setStats).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error-box">{error}</div>;
  if (!stats) return <div className="loading-block"><span className="spinner" /> Loading dashboard…</div>;

  const pendingPlans = (stats.plans_by_status["submitted"] ?? 0) + (stats.plans_by_status["draft"] ?? 0);

  return (
    <>
      <div className="row-between mb-sm">
        <h2 style={{ margin: 0 }}>Plant Overview</h2>
        <span className="muted">All metrics update live</span>
      </div>
      <div className="stat-row">
        <div className="stat">
          <div className="label">Plans total</div>
          <div className="value">{stats.total_plans}</div>
          <div className="muted">{pendingPlans} awaiting action</div>
        </div>
        <div className="stat">
          <div className="label">Inspections</div>
          <div className="value">{stats.total_inspections}</div>
          <div className="muted">{(stats.defect_rate * 100).toFixed(1)}% fail rate</div>
        </div>
        <div className="stat">
          <div className="label">KB documents</div>
          <div className="value">{stats.total_documents}</div>
          <div className="muted">grounding corpus</div>
        </div>
        <div className="stat">
          <div className="label">Avg feedback</div>
          <div className="value ok">{stats.avg_plan_rating ? stats.avg_plan_rating.toFixed(1) : "—"}</div>
          <div className="muted">{stats.total_feedback} reviews (1–5)</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">Plan pipeline</div>
          {Object.keys(stats.plans_by_status).length === 0 && <div className="muted">No plans yet.</div>}
          {Object.entries(stats.plans_by_status).map(([status, count]) => (
            <div key={status} className="row-between" style={{ padding: "6px 0" }}>
              <span className={`badge ${status === "approved" ? "ok" : status === "rejected" ? "err" : status === "submitted" ? "warn" : "dim"}`}>
                {status}
              </span>
              <strong>{count}</strong>
            </div>
          ))}
          <div className="mt">
            <Link to="/plans"><button className="btn secondary sm">Open plans →</button></Link>
          </div>
        </div>

        <div className="card">
          <div className="card-title">Recent approvals</div>
          {stats.recent_approvals.length === 0 && <div className="muted">No approval activity yet.</div>}
          {stats.recent_approvals.map((a) => (
            <div key={a.id} className="row-between" style={{ padding: "6px 0", borderBottom: "1px solid rgba(45,55,72,.4)" }}>
              <span>
                <span className={`badge ${a.action === "approve" ? "ok" : a.action === "reject" ? "err" : "dim"}`}>{a.action}</span>{" "}
                {a.actor_name || a.id}
              </span>
              <span className="muted">{new Date(a.created_at).toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Quick actions</div>
        <div className="row">
          <Link to="/plans"><button className="btn">＋ Generate process plan</button></Link>
          <Link to="/inspections"><button className="btn secondary">🔍 Inspect part image</button></Link>
          <Link to="/"><button className="btn secondary">✳ Ask Mechanical Copilot</button></Link>
          <Link to="/documents"><button className="btn secondary">📚 Manage documents</button></Link>
        </div>
      </div>
    </>
  );
}
