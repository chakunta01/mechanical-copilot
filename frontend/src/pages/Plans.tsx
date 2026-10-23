import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ProcessPlan } from "../api";

const STATUS_BADGE: Record<string, string> = {
  draft: "dim",
  submitted: "warn",
  approved: "ok",
  rejected: "err",
  archived: "dim",
};

export function PlansPage() {
  const [plans, setPlans] = useState<ProcessPlan[]>([]);
  const [showGen, setShowGen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // generator form state
  const [partNumber, setPartNumber] = useState("");
  const [material, setMaterial] = useState("");
  const [quantity, setQuantity] = useState(25);
  const [tolerances, setTolerances] = useState("");
  const [finish, setFinish] = useState("");
  const [features, setFeatures] = useState("");
  const [specials, setSpecials] = useState("");
  const [notes, setNotes] = useState("");

  const load = () => api.listPlans().then((r) => setPlans(r.items)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const plan = await api.generatePlan({
        part_number: partNumber,
        material,
        quantity,
        tolerance_notes: tolerances,
        surface_finish: finish,
        features: features.split(",").map((s) => s.trim()).filter(Boolean),
        special_requirements: specials.split(",").map((s) => s.trim()).filter(Boolean),
        notes,
      });
      setShowGen(false);
      window.location.href = `/plans/${plan.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="row-between mb-sm">
        <h2 style={{ margin: 0 }}>Process Plans</h2>
        <button className="btn" onClick={() => setShowGen(!showGen)}>{showGen ? "Close" : "＋ Generate plan"}</button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {showGen && (
        <form className="card" onSubmit={generate}>
          <div className="card-title">New plan — requirements</div>
          <div className="grid-2">
            <label className="field">
              <span>Part number *</span>
              <input required value={partNumber} onChange={(e) => setPartNumber(e.target.value)} placeholder="SHF-350-A" />
            </label>
            <label className="field">
              <span>Material</span>
              <input value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="C45 steel" />
            </label>
            <label className="field">
              <span>Quantity</span>
              <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
            </label>
            <label className="field">
              <span>Surface finish</span>
              <input value={finish} onChange={(e) => setFinish(e.target.value)} placeholder="Ra 0.8 on bearing seats" />
            </label>
            <label className="field">
              <span>Tolerance notes</span>
              <input value={tolerances} onChange={(e) => setTolerances(e.target.value)} placeholder="Ø24.00 h6, length 50 ±0.1" />
            </label>
            <label className="field">
              <span>Features (comma-separated)</span>
              <input value={features} onChange={(e) => setFeatures(e.target.value)} placeholder="6 mm keyway, 4x Ø5 holes" />
            </label>
            <label className="field">
              <span>Special requirements (comma-separated)</span>
              <input value={specials} onChange={(e) => setSpecials(e.target.value)} placeholder="material certification" />
            </label>
            <label className="field">
              <span>Notes</span>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="anything else the planner should know" />
            </label>
          </div>
          <button className="btn" disabled={busy}>{busy ? <><span className="spinner" /> Generating grounded draft…</> : "Generate draft plan"}</button>
          <div className="muted mt">The draft is generated from your knowledge base, validated against plant rules, and lands in <strong>Draft</strong> for engineer review.</div>
        </form>
      )}

      <div className="card">
        {plans.length === 0 ? (
          <div className="empty-state">
            <div className="big">📋</div>
            No plans yet. Generate the first draft plan for a part.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Plan</th><th>Part</th><th>Material</th><th>Qty</th><th>Rules</th><th>Grounding</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/plans/${p.id}`}>{p.title}</Link></td>
                  <td className="mono">{p.part_number}</td>
                  <td>{p.material || "—"}</td>
                  <td>{p.quantity}</td>
                  <td>{p.validation?.ok ? <span className="badge ok">pass</span> : <span className="badge err">{p.validation?.errors?.length ?? 0} errors</span>}</td>
                  <td>
                    <span className="badge info">{p.grounding?.operations_with_citations ?? 0}/{p.grounding?.total_operations ?? 0} ops cited</span>
                    {(p.grounding?.unsupported_claims?.length ?? 0) > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>{p.grounding.unsupported_claims.length} unverified</span>}
                  </td>
                  <td><span className={`badge ${STATUS_BADGE[p.status] ?? "dim"}`}>{p.status}</span></td>
                  <td><Link to={`/plans/${p.id}`}><button className="btn secondary sm">Open</button></Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
