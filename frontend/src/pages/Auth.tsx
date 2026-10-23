import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../main";

export function AuthPage() {
  const { login, register } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
      nav("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>⚙ MFG Copilot</h1>
        <div className="sub">Process planning & quality inspection, grounded in your plant knowledge.</div>
        {error && <div className="error-box">{error}</div>}
        {mode === "register" && (
          <label className="field">
            <span>Full name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Engineer" />
          </label>
        )}
        <label className="field">
          <span>Email</span>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@plant.com" />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="min. 10 characters"
          />
        </label>
        <button className="btn" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>
          {busy ? <span className="spinner" /> : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <div className="auth-switch">
          {mode === "login" ? (
            <>
              New here? <a href="#" onClick={(e) => { e.preventDefault(); setMode("register"); }}>Create an account</a>
              <div className="muted mt">The first account created becomes the plant admin.</div>
            </>
          ) : (
            <>
              Have an account? <a href="#" onClick={(e) => { e.preventDefault(); setMode("login"); }}>Sign in</a>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
