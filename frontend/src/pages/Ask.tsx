import { useRef, useState } from "react";
import { api, type Citation } from "../api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  confidence?: number;
  refused?: boolean;
  mode?: "grounded" | "general";
}

export function AskPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const res = await api.qaAsk(q, threadId);
      setThreadId(res.thread_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          citations: res.citations,
          confidence: res.confidence,
          refused: res.refused,
          mode: res.mode,
        },
      ]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "failed"}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  };

  return (
    <>
      <h2 style={{ marginTop: 0 }}>Ask the Copilot</h2>
      <div className="muted mb-sm">
        Manufacturing questions are answered ONLY from your approved documents, with citations. Anything outside the
        knowledge base is answered from the assistant's broad expertise and clearly labeled "General knowledge" —
        verify plant-specific rules against controlled documents.
      </div>

      <div className="card chat-window">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="big">💬</div>
              Try: "What spindle RPM is approved for roughing steel on a VMC?", "What are the acceptance criteria for scratches?" — or anything general, like "Explain GD&T datums" or "Plan a weekend trip".
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`chat-bubble ${m.role} ${m.refused ? "refusal" : ""}`}>
              {m.content}
              {m.mode === "general" && (
                <span className="chat-citation">
                  <span className="citation-chip">🌐 General knowledge — not from your documents</span>
                </span>
              )}
              {m.citations && m.citations.length > 0 && (
                <span className="chat-citation">
                  Sources:{" "}
                  {m.citations.map((c, j) => (
                    <span key={j} className="citation-chip" title={c.snippet}>
                      {c.source_ref || c.title} v{c.version} ({(c.score * 100).toFixed(0)}%)
                    </span>
                  ))}
                  {typeof m.confidence === "number" && <span style={{ marginLeft: 6 }}>confidence {(m.confidence * 100).toFixed(0)}%</span>}
                </span>
              )}
            </div>
          ))}
          {busy && <div className="loading-block"><span className="spinner" /> Thinking…</div>}
          <div ref={endRef} />
        </div>
        <form className="chat-input-row" onSubmit={ask}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything — SOPs, acceptance criteria… or any general question"
          />
          <button className="btn" disabled={busy || !input.trim()}>Ask</button>
        </form>
      </div>
    </>
  );
}
