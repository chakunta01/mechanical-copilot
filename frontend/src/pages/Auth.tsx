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
  const [adminBootstrapToken, setAdminBootstrapToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name, adminBootstrapToken);
      nav("/");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Authentication failed";
      setError(mode === "login" && message === "Invalid email or password"
        ? "Email or password did not match. If this is your first visit, create an account below."
        : message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>⚙ Mechanical Copilot</h1>
        <div className="sub">Mechanical engineering answers for design, vehicles, manufacturing, and thermal systems.</div>
        {error && <div className="error-box">{error}</div>}
        {mode === "register" && (
          <>
            <label className="field">
              <span>Full name</span>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Engineer" />
            </label>
            <label className="field">
              <span>Site admin setup token <small>(optional; leave blank for a standard account)</small></span>
              <input type="password" autoComplete="off" value={adminBootstrapToken} onChange={(e) => setAdminBootstrapToken(e.target.value)} placeholder="Only for the site administrator" />
            </label>
          </>
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
              <div className="muted mt">Create an account before signing in. Standard accounts do not need an admin setup token.</div>
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
