import { useEffect, useRef, useState } from "react";
import { api, type Citation, type DocumentRec } from "../api";

export function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRec[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [results, setResults] = useState<Citation[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // add-document form
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("sop");
  const [sourceRef, setSourceRef] = useState("");
  const [version, setVersion] = useState("v1");
  const [content, setContent] = useState("");

  const load = () => api.listDocuments().then((r) => setDocs(r.items)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api.createDocument({ title, doc_type: docType, source_ref: sourceRef, version, content });
      setTitle("");
      setContent("");
      setSourceRef("");
      setShowAdd(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add document");
    }
  };

  const upload = async (file: File) => {
    setError("");
    try {
      await api.uploadDocument(file, docType, sourceRef);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  };

  const doSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQ.trim()) return;
    const r = await api.search(searchQ);
    setResults(r.chunks);
  };

  return (
    <>
      <div className="row-between mb-sm">
        <h2 style={{ margin: 0 }}>Knowledge Base</h2>
        <button className="btn" onClick={() => setShowAdd(!showAdd)}>{showAdd ? "Close" : "＋ Add document"}</button>
      </div>
      {error && <div className="error-box">{error}</div>}

      {showAdd && (
        <form className="card" onSubmit={add}>
          <div className="card-title">Add document (text)</div>
          <div className="grid-2">
            <label className="field"><span>Title *</span>
              <input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="SOP-MILL-001: General Milling" /></label>
            <label className="field"><span>Type</span>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                <option value="sop">SOP</option>
                <option value="routing">Routing</option>
                <option value="standard">Quality standard</option>
                <option value="lesson">Lesson learned</option>
                <option value="qa">Control plan</option>
              </select></label>
            <label className="field"><span>Source reference</span>
              <input value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} placeholder="SOP-MILL-001 §3" /></label>
            <label className="field"><span>Version</span>
              <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="v2.1" /></label>
          </div>
          <label className="field"><span>Content *</span>
            <textarea rows={8} required value={content} onChange={(e) => setContent(e.target.value)}
              placeholder="Paste the document text. Headings like 'SECTION 3: ...' improve chunking." /></label>
          <div className="row">
            <button className="btn" type="submit">Ingest into KB</button>
            <button className="btn secondary" type="button" onClick={() => fileRef.current?.click()}>…or upload .txt/.md/.pdf/.docx</button>
            <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.docx" style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }} />
          </div>
        </form>
      )}

      <form className="card" onSubmit={doSearch}>
        <div className="card-title">Test retrieval</div>
        <div className="row">
          <input style={{ flex: 1 }} value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
            placeholder="e.g. titanium spindle speed limit" />
          <button className="btn secondary">Search KB</button>
        </div>
        {results && (
          <div className="mt">
            {results.length === 0 && <div className="muted">No chunks matched. Try different wording or ingest more documents.</div>}
            {results.map((c) => (
              <div key={c.chunk_id} className="issue-row">
                <span className="citation-chip">{(c.score * 100).toFixed(0)}%</span>
                <span className="mono">{c.source_ref || c.title}</span>
                <span className="muted">{c.snippet.slice(0, 140)}…</span>
              </div>
            ))}
          </div>
        )}
      </form>

      <div className="card">
        <div className="card-title">Documents ({docs.length})</div>
        {docs.length === 0 ? (
          <div className="empty-state"><div className="big">📚</div>
            The knowledge base is empty. Add your SOPs, routings, standards and lessons learned — every generated plan and answer cites them.</div>
        ) : (
          <table className="table">
            <thead><tr><th>Title</th><th>Type</th><th>Ref</th><th>Ver</th><th>Chunks</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td><span className="badge dim">{d.doc_type}</span></td>
                  <td className="mono">{d.source_ref || "—"}</td>
                  <td>{d.version}</td>
                  <td>{d.chunk_count}</td>
                  <td>
                    <span className={`badge ${d.status === "ingested" ? "ok" : d.status === "failed" ? "err" : "warn"}`}>{d.status}</span>
                    {d.error && <div className="muted">{d.error.slice(0, 80)}</div>}
                  </td>
                  <td><button className="btn danger sm" onClick={() => api.deleteDocument(d.id).then(load)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
