import React, { createContext, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { api, type User } from "./api";
import { AskPage } from "./pages/Ask";
import { AuthPage } from "./pages/Auth";

// --------------------------------------------------------------------------- //
// Auth context
// --------------------------------------------------------------------------- //
interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string, adminBootstrapToken: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthCtx>(null as unknown as AuthCtx);
export const useAuth = () => useContext(AuthContext);

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!localStorage.getItem("copilot.access")) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem("copilot.access");
        localStorage.removeItem("copilot.refresh");
      })
      .finally(() => setLoading(false));
  }, []);

  const ctx: AuthCtx = {
    user,
    loading,
    login: async (email, password) => {
      const pair = await api.login(email, password);
      localStorage.setItem("copilot.access", pair.access_token);
      localStorage.setItem("copilot.refresh", pair.refresh_token);
      setUser(await api.me());
    },
    register: async (email, password, name, adminBootstrapToken) => {
      const pair = await api.register(email, password, name, adminBootstrapToken);
      localStorage.setItem("copilot.access", pair.access_token);
      localStorage.setItem("copilot.refresh", pair.refresh_token);
      setUser(await api.me());
    },
    logout: () => {
      localStorage.removeItem("copilot.access");
      localStorage.removeItem("copilot.refresh");
      setUser(null);
    },
  };
  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  return (
      <div className="main copilot-app-main">
        <header className="topbar copilot-topbar">
          <Link to="/" className="topbar-brand">
            <span className="logo">⚙</span>
            <span className="brand-wordmark"><strong>Mechanical Copilot</strong><small>ENGINEERING STUDIO</small></span>
          </Link>
          <div className="topbar-user">
            <span>{user?.full_name || user?.email}</span>
            <button className="btn secondary sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <div className="page copilot-page">{children}</div>
      </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="loading-block"><span className="spinner" /> Loading…</div>;
  if (!user) return <Navigate to="/auth" replace />;
  return <Shell>{children}</Shell>;
}

// --------------------------------------------------------------------------- //
// App
// --------------------------------------------------------------------------- //
function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="*" element={<RequireAuth><Routes>
            <Route path="/" element={<AskPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes></RequireAuth>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
