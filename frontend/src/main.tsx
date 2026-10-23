import React, { createContext, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type User } from "./api";
import { DashboardPage } from "./pages/Dashboard";
import { DocumentsPage } from "./pages/Documents";
import { PlansPage } from "./pages/Plans";
import { PlanDetailPage } from "./pages/PlanDetail";
import { InspectionsPage } from "./pages/Inspections";
import { AskPage } from "./pages/Ask";
import { AuthPage } from "./pages/Auth";

// --------------------------------------------------------------------------- //
// Auth context
// --------------------------------------------------------------------------- //
interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
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
    register: async (email, password, name) => {
      const pair = await api.register(email, password, name);
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

// --------------------------------------------------------------------------- //
// Layout
// --------------------------------------------------------------------------- //
const NAV = [
  { to: "/", label: "Dashboard", icon: "▦" },
  { to: "/plans", label: "Process Plans", icon: "📋" },
  { to: "/inspections", label: "Inspections", icon: "🔍" },
  { to: "/ask", label: "Ask the KB", icon: "💬" },
  { to: "/documents", label: "Knowledge Base", icon: "📚" },
];

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="logo">⚙</span> MFG Copilot
        </div>
        <nav className="sidebar-nav">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`nav-item ${location.pathname === n.to ? "active" : ""}`}>
              <span>{n.icon}</span> {n.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div>{user?.full_name || user?.email}</div>
          <div style={{ opacity: 0.6 }}>{user?.role}</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title">AI Copilot for Manufacturing Process Planning & Quality Inspection</div>
          <div className="topbar-user">
            <span>{user?.email}</span>
            <button className="btn secondary sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <div className="page">{children}</div>
      </div>
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
            <Route path="/" element={<DashboardPage />} />
            <Route path="/plans" element={<PlansPage />} />
            <Route path="/plans/:id" element={<PlanDetailPage />} />
            <Route path="/inspections" element={<InspectionsPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
          </Routes></RequireAuth>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
