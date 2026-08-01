import { useState, FormEvent } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { Shield, Loader, AlertCircle, Eye, EyeOff } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";

export default function Login() {
  const { login, isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!loading && isAuthenticated) return <Navigate to="/dashboard" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate("/dashboard", { replace: true });
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        (err?.response?.status === 401
          ? "Email ou mot de passe incorrect"
          : "Échec de la connexion. Réessayez.");
      setError(typeof msg === "string" ? msg : "Échec de la connexion.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-dark-900 px-4"
      style={{ background: "var(--page-glow)" }}
    >
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm bg-dark-800 border border-white/5 rounded-2xl p-9 shadow-2xl"
      >
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-brand-600/15 mb-3">
            <Shield className="text-brand-500" size={28} />
          </div>
          <h1 className="text-brand-500 text-2xl font-extrabold tracking-tight">Sentinelle</h1>
          <p className="text-gray-500 text-xs mt-1">Community Intelligence</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 text-red-300 text-sm rounded-lg px-3 py-2.5 mb-5">
            <AlertCircle size={16} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <label className="block text-sm text-gray-400 font-medium mb-1.5">Adresse e-mail</label>
        <input
          type="email"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="manager@medianet.tn"
          className="w-full bg-dark-900 border border-white/10 rounded-lg px-3.5 py-2.5 text-sm text-gray-100 placeholder-gray-600 mb-4 focus:outline-none focus:border-brand-500"
        />

        <label className="block text-sm text-gray-400 font-medium mb-1.5">Mot de passe</label>
        <div className="relative mb-6">
          <input
            type={showPwd ? "text" : "password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full bg-dark-900 border border-white/10 rounded-lg px-3.5 py-2.5 pr-10 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-brand-500"
          />
          <button
            type="button"
            onClick={() => setShowPwd((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
            tabIndex={-1}
          >
            {showPwd ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white font-semibold text-sm py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          {submitting && <Loader size={16} className="animate-spin" />}
          {submitting ? "Connexion..." : "Se connecter"}
        </button>

        <p className="text-center text-gray-600 text-xs mt-5">
          Authentification sécurisée par jeton JWT
        </p>
      </form>
    </div>
  );
}
