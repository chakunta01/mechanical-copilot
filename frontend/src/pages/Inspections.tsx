import { useEffect, useRef, useState } from "react";
import { api, type Inspection } from "../api";

export function InspectionsPage() {
  const [items, setItems] = useState<Inspection[]>([]);
  const [current, setCurrent] = useState<Inspection | null>(null);
  const [partNumber, setPartNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dispositionNotes, setDispositionNotes] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.listInspections().then((r) => setItems(r.items)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const analyze = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const insp = await api.analyzeImage(file, partNumber);
      setCurrent(insp);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  };

  const setDisp = async (d: string) => {
    if (!current) return;
    const updated = await api.setDisposition(current.id, d, dispositionNotes);
    setCurrent(updated);
    load();
  };

  return (
    <>
      <div className="row-between mb-sm">
        <h2 style={{ margin: 0 }}>Visual Quality Inspection</h2>
      </div>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <div className="card-title">Analyze a part image</div>
        <div className="row">
          <input
            type="text"
            placeholder="Part number (optional)"
            value={partNumber}
            onChange={(e) => setPartNumber(e.target.value)}
            style={{ width: 220 }}
          />
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) analyze(f);
            }}
            style={{ display: "none" }}
          />
          <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? <><span className="spinner" /> Analyzing…</> : "📷 Upload & analyze"}
          </button>
        </div>
        <div className="muted mt">
          Every image passes a deterministic quality gate (resolution, brightness, sharpness, glare) before the vision
          model runs. Unusable images are refused with reasons instead of guessed verdicts.
        </div>
      </div>

      {current && <InspectionDetail insp={current} onDispose={setDisp} notes={dispositionNotes} setNotes={setDispositionNotes} />}

      <div className="card">
        <div className="card-title">Inspection history</div>
        {items.length === 0 ? (
          <div className="empty-state"><div className="big">🔍</div>No inspections yet.</div>
        ) : (
          <table className="table">
            <thead><tr><th>When</th><th>Part</th><th>Verdict</th><th>Defects</th><th>Quality gate</th><th>Disposition</th><th></th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td className="muted">{new Date(i.created_at).toLocaleString()}</td>
                  <td className="mono">{i.part_number || "—"}</td>
                  <td>
                    <span className={`badge ${i.result?.verdict === "pass" ? "ok" : i.result?.verdict === "fail" ? "err" : "warn"}`}>
                      {i.result?.verdict ?? i.status}
                    </span>
                  </td>
                  <td>{i.result?.defects?.length ?? 0}</td>
                  <td>{i.quality?.passed ? <span className="badge ok">passed</span> : <span className="badge warn">failed</span>}</td>
                  <td>
                    {i.disposition !== "pending"
                      ? <span className={`badge ${i.disposition === "accept" ? "ok" : "err"}`}>{i.disposition}</span>
                      : <span className="badge dim">pending</span>}
                  </td>
                  <td><button className="btn secondary sm" onClick={() => setCurrent(i)}>View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function InspectionDetail({
  insp,
  onDispose,
  notes,
  setNotes,
}: {
  insp: Inspection;
  onDispose: (d: string) => void;
  notes: string;
  setNotes: (s: string) => void;
}) {
  const r = insp.result ?? {};
  const [imageUrl, setImageUrl] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    api.inspectionImage(insp.id).then((url) => {
      objectUrl = url;
      if (active) setImageUrl(url);
      else URL.revokeObjectURL(url);
    }).catch(() => setImageUrl(""));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [insp.id]);
  return (
    <div className="insp-layout">
      <div>
        <div className="card">
          <div className="card-title">Image (quality gate: {insp.quality?.passed ? "PASSED" : "FAILED"})</div>
          <div className="image-frame">
            {imageUrl ? <img src={imageUrl} alt="part under inspection" /> : <div className="empty-state">Loading private inspection image…</div>}
          </div>
          {insp.quality && (
            <div className="mt">
              {Object.entries(insp.quality.checks).map(([k, v]) => (
                <div key={k} className="row-between" style={{ padding: "3px 0", fontSize: 12 }}>
                  <span className="muted">{k}</span>
                  <span>{v.detail} {v.passed ? "✓" : "✗"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div>
        <div className="card">
          <div className="row-between">
            <div className="card-title" style={{ margin: 0 }}>Verdict</div>
            <span className={`badge ${r.verdict === "pass" ? "ok" : r.verdict === "fail" ? "err" : "warn"}`} style={{ fontSize: 13 }}>
              {String(r.verdict ?? "—").toUpperCase()}
            </span>
          </div>
          {typeof r.confidence === "number" && (
            <div className="mt">
              <div className="muted">Model confidence: {(r.confidence * 100).toFixed(0)}%</div>
              <div className="conf-bar"><div style={{ width: `${(r.confidence ?? 0) * 100}%` }} /></div>
            </div>
          )}
          {r.explanation && <div style={{ marginTop: 10, fontSize: 13 }}>{r.explanation}</div>}
        </div>

        {(r.defects ?? []).length > 0 && (
          <div className="card">
            <div className="card-title">Detected defects</div>
            {r.defects!.map((d, i) => (
              <div key={i} className="defect-card">
                <div className="head">
                  <strong>{d.defect_type}</strong>
                  <span className={`sev-${d.severity}`}>severity: {d.severity}{d.below_threshold ? " · below threshold" : ""}</span>
                </div>
                <div className="muted">{d.location}</div>
                {d.evidence && <div style={{ fontSize: 13, marginTop: 4 }}>{d.evidence}</div>}
                <div className="conf-bar"><div className={d.confidence < 0.6 ? "low" : ""} style={{ width: `${d.confidence * 100}%` }} /></div>
                <div className="muted" style={{ marginTop: 2 }}>confidence {(d.confidence * 100).toFixed(0)}%</div>
              </div>
            ))}
          </div>
        )}

        {(r.references ?? []).length > 0 && (
          <div className="card">
            <div className="card-title">Sources consulted</div>
            {r.references!.map((c, i) => (
              <div key={i} className="issue-row"><span className="citation-chip">{c.source_ref || c.title}</span><span className="muted">{c.snippet.slice(0, 110)}…</span></div>
            ))}
          </div>
        )}

        {insp.disposition === "pending" && (
          <div className="card">
            <div className="card-title">Human disposition (required)</div>
            <label className="field">
              <span>Notes</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Inspector notes for the record…" />
            </label>
            <div className="row">
              <button className="btn ok" onClick={() => onDispose("accept")}>Accept</button>
              <button className="btn danger" onClick={() => onDispose("reject")}>Reject</button>
              <button className="btn secondary" onClick={() => onDispose("rework")}>Send to rework</button>
            </div>
          </div>
        )}
        {insp.disposition !== "pending" && (
          <div className="card">
            <div className="card-title">Disposition</div>
            <span className={`badge ${insp.disposition === "accept" ? "ok" : "err"}`}>{insp.disposition}</span>
            <span className="muted" style={{ marginLeft: 10 }}>by {insp.reviewed_by}</span>
          </div>
        )}
      </div>
    </div>
  );
}
