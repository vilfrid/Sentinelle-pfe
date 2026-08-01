import { NavLink } from "react-router-dom";
import { clsx } from "clsx";
import {
  LayoutDashboard, Megaphone, Users2, MessageSquare,
  BarChart3, FileText, GitMerge, Terminal, LogOut, Sun, Moon
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useTheme } from "../contexts/ThemeContext";

const NAV = [
  { to: "/dashboard",  icon: LayoutDashboard, label: "Dashboard" },
  { to: "/campaigns",  icon: Megaphone,        label: "Campaigns" },
  { to: "/creators",   icon: Users2,           label: "Creators" },
  { to: "/comments",   icon: MessageSquare,    label: "Comments" },
  { to: "/analytics",  icon: BarChart3,        label: "Analytics" },
  { to: "/reports",    icon: FileText,         label: "Reports" },
  { to: "/matching",   icon: GitMerge,         label: "Matching" },
  { to: "/pipeline",   icon: Terminal,         label: "Pipeline" },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  return (
    <aside className="w-60 bg-dark-800 border-r border-white/5 flex flex-col shrink-0">
      <div className="px-6 py-5 border-b border-white/5 flex items-start justify-between gap-2">
        <div>
          <span className="text-brand-500 font-bold text-xl tracking-tight">Sentinelle</span>
          <p className="text-xs text-gray-500 mt-0.5">Community Intelligence</p>
        </div>
        <button
          onClick={toggleTheme}
          title={theme === "dark" ? "Passer en mode clair" : "Passer en mode sombre"}
          className="p-2 -mr-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors shrink-0"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>

      <nav className="flex-1 py-4 px-3 space-y-0.5">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-600/20 text-brand-400"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              )
            }
          >
            <Icon size={17} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 pb-5">
        <div className="bg-dark-700 rounded-lg px-3 py-2.5 space-y-1.5">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Pipeline</p>
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Celery Worker
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <div className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
            AI Engine
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-white/5">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-gray-300 truncate">
                {user?.full_name || user?.email || "Utilisateur"}
              </p>
              <p className="text-[10px] text-gray-500 uppercase tracking-wider">
                {user?.role || ""}
              </p>
            </div>
            <button
              onClick={logout}
              title="Se déconnecter"
              className="p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors shrink-0"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
