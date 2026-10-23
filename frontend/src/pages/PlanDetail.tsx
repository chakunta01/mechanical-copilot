import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type ProcessPlan } from "../api";
import { useAuth } from "../main";

export function PlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [plan, setPlan] = useState<ProcessPlan | null>(null);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [rating, setRating] = useState(4);

  const load = () => {
    if (!id) return;
    api.getPlan(id).then(setPlan).catch((e) => setError(e.message));
  };
  useEffect(load, [id]);

  if (error) return <div className="error-box">{error}</div>;
  if (!plan) return <div className="loading-block"><span className="spinner" /> Loading plan…</div>;

  const v = plan.validation;
  const g = plan.grounding;
  const canDecide = user?.role === "admin" || user?.role === "engineer";

  const decide = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      const updated = await api.decidePlan(plan.id, action, comment);
      setPlan(updated);
      setComment("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const sendFeedback = async () => {
    await api.sendFeedback({ target_type: "plan", target_id: plan.id, rating, category: "usefulness", notes: comment });
    setFeedbackSent(true);
  };

  return (
    <>
      <div className="row-between mb-sm">
        <div>
          <h2 style={{ margin: 0 }}>{plan.title}</h2>
          <span className="muted">
            <span className="mono">{plan.id}</span> · v{plan.version} · created {new Date(plan.created_at).toLocaleString()}
          </span>
        </div>
        <div className="row">
          <span className={`badge ${plan.status === "approved" ? "ok" : plan.status === "rejected" ? "err" : plan.status === "submitted" ? "warn" : "dim"}`}>
            {plan.status}
          </span>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      {/* Summary strip */}
      <div className="stat-row">
        <div className="stat">
          <div className="label">Rule validation</div>
          <div className={`value ${v?.ok ? "ok" : "err"}`}>{v?.ok ? "PASS" : "FAIL"}</div>
          <div className="muted">{v?.errors?.length ?? 0} errors · {v?.warnings?.length ?? 0} warnings</div>
        </div>
        <div className="stat">
          <div className="label">Grounding</div>
          <div className="value">{g?.citation_count ?? 0}</div>
          <div className="muted">{g?.operations_with_citations ?? 0}/{g?.total_operations ?? 0} ops carry citations</div>
        </div>
        <div className="stat">
          <div className="label">Part</div>
          <div className="value" style={{ fontSize: 18 }}>{plan.part_number}</div>
          <div className="muted">{plan.material || "material unspecified"} · qty {plan.quantity}</div>
        </div>
        <div className="stat">
          <div className="label">Unverified specs</div>
          <div className={`value ${(g?.unsupported_claims?.length ?? 0) > 0 ? "err" : "ok"}`}>{g?.unsupported_claims?.length ?? 0}</div>
          <div className="muted">numeric claims lacking KB support</div>
        </div>
      </div>

      {/* Validation issues */}
      {((v?.errors?.length ?? 0) > 0 || (v?.warnings?.length ?? 0) > 0) && (
        <div className="card">
          <div className="card-title">Rule validation report</div>
          {[...(v?.errors ?? []), ...(v?.warnings ?? [])].map((i, idx) => (
            <div key={idx} className="issue-row">
              <span className={`badge ${i.severity === "error" ? "err" : "warn"}`}>{i.severity}</span>
              <span className="rule-id">{i.rule_id}</span>
              <span>{i.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Unsupported claims */}
      {(g?.unsupported_claims?.length ?? 0) > 0 && (
        <div className="card">
          <div className="card-title">⚠ Unverified numeric specifications</div>
          <div className="muted mb-sm">These values in the draft have no support in the retrieved knowledge. Verify against drawing/SOP before release.</div>
          {g.unsupported_claims.map((c, i) => (
            <div key={i} className="issue-row"><span className="badge warn">unverified</span><span className="mono">{c}</span></div>
          ))}
        </div>
      )}

      {/* Operations */}
      <div className="card">
        <div className="card-title">Operations</div>
        {plan.plan.operations.map((op) => (
          <div key={op.op_number} className="op-card">
            <div className="op-head">
              <span className="op-num">OP {op.op_number}</span>
              <strong>{op.name}</strong>
              <span className="op-machine">on {op.machine}</span>
            </div>
            {op.description && <div style={{ fontSize: 13 }}>{op.description}</div>}
            {op.tooling.length > 0 && <div className="muted mt" style={{ marginTop: 4 }}>Tooling: {op.tooling.join(", ")}</div>}
            {Object.keys(op.parameters).length > 0 && (
              <div className="op-params">
                {Object.entries(op.parameters).map(([k, val]) => (
                  <span key={k} className="op-param">{k}: {String(val)}</span>
                ))}
              </div>
            )}
            {op.inspection_checkpoints.length > 0 && (
              <div className="mt" style={{ marginTop: 6, fontSize: 12 }}>
                <span className="muted">Checkpoints: </span>
                {op.inspection_checkpoints.join(" · ")}
              </div>
            )}
            {op.citations.length > 0 && (
              <div style={{ marginTop: 6 }}>
                {op.citations.map((c, i) => (
                  <span key={i} className="citation-chip" title={c.snippet}>{c.source_ref || c.title} v{c.version}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="grid-2">
        {/* Inspection plan */}
        <div className="card">
          <div className="card-title">Inspection plan</div>
          <table className="table">
            <thead><tr><th>Characteristic</th><th>Method</th><th>Frequency</th><th>Acceptance</th></tr></thead>
            <tbody>
              {plan.plan.inspection_plan.map((it, i) => (
                <tr key={i}>
                  <td>{it.characteristic}</td>
                  <td>{it.method}</td>
                  <td>{it.frequency}</td>
                  <td className="mono">{it.acceptance_criteria}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Assumptions & risks */}
        <div>
          <div className="card">
            <div className="card-title">Assumptions</div>
            {(plan.plan.assumptions ?? []).length === 0 && <div className="muted">None recorded.</div>}
            {(plan.plan.assumptions ?? []).map((a, i) => <div key={i} style={{ fontSize: 13 }}>• {a}</div>)}
          </div>
          <div className="card">
            <div className="card-title">Risk notes</div>
            {(plan.plan.risk_notes ?? []).length === 0 && <div className="muted">None recorded.</div>}
            {(plan.plan.risk_notes ?? []).map((r, i) => <div key={i} style={{ fontSize: 13 }}>• {r}</div>)}
          </div>
        </div>
      </div>

      {/* Human-in-the-loop actions */}
      {canDecide && (
        <div className="card">
          <div className="card-title">Human-in-the-loop decision</div>
          <label className="field">
            <span>Comment (required for reject)</span>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Review notes, rejection reason, or edit rationale…" />
          </label>
          <div className="row">
            {plan.status === "draft" && <button className="btn" disabled={busy} onClick={() => decide("submit")}>Submit for approval</button>}
            {plan.status === "draft" && <button className="btn secondary" disabled={busy} onClick={() => decide("revise")}>Save revision</button>}
            {plan.status === "submitted" && <button className="btn ok" disabled={busy} onClick={() => decide("approve")}>✓ Approve</button>}
            {plan.status === "submitted" && <button className="btn danger" disabled={busy} onClick={() => decide("reject")}>✗ Reject</button>}
            {plan.status === "rejected" && <button className="btn" disabled={busy} onClick={() => decide("revise")}>Revise (back to draft)</button>}
            {plan.status === "approved" && <button className="btn secondary" disabled={busy} onClick={() => api.duplicatePlan(plan.id).then((p) => (window.location.href = `/plans/${p.id}`))}>Fork as new draft</button>}
          </div>
          {plan.status === "rejected" && plan.rejected_reason && (
            <div className="muted mt">Rejection reason: {plan.rejected_reason}</div>
          )}
        </div>
      )}

      {/* Approval history */}
      <div className="card">
        <div className="card-title">Approval & audit trail</div>
        <ApprovalTrail planId={plan.id} />
      </div>

      {/* Feedback */}
      <div className="card">
        <div className="card-title">Engineer feedback (feeds continuous improvement)</div>
        {feedbackSent ? (
          <span className="badge ok">Feedback recorded — thank you</span>
        ) : (
          <div className="row">
            <select value={rating} onChange={(e) => setRating(Number(e.target.value))} style={{ width: 200 }}>
              <option value={5}>5 — ready to release</option>
              <option value={4}>4 — minor edits</option>
              <option value={3}>3 — needs rework</option>
              <option value={2}>2 — major gaps</option>
              <option value={1}>1 — unusable</option>
            </select>
            <button className="btn secondary" onClick={sendFeedback}>Submit rating</button>
          </div>
        )}
      </div>
    </>
  );
}

function ApprovalTrail({ planId }: { planId: string }) {
  const [items, setItems] = useState<{ id: string; action: string; actor_name: string; comment: string; created_at: string }[]>([]);
  useEffect(() => {
    api.planApprovals(planId).then((r) => setItems(r.items)).catch(() => {});
  }, [planId]);
  if (items.length === 0) return <div className="muted">No actions recorded yet.</div>;
  return (
    <table className="table">
      <thead><tr><th>Action</th><th>Actor</th><th>Comment</th><th>When</th></tr></thead>
      <tbody>
        {items.map((a) => (
          <tr key={a.id}>
            <td><span className={`badge ${a.action === "approve" ? "ok" : a.action === "reject" ? "err" : "dim"}`}>{a.action}</span></td>
            <td>{a.actor_name}</td>
            <td>{a.comment || "—"}</td>
            <td className="muted">{new Date(a.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
