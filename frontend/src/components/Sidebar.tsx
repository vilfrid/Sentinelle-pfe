import { NavLink } from "react-router-dom";
import { clsx } from "clsx";
import {
  LayoutDashboard, Megaphone, Users2, MessageSquare,
  BarChart3, FileText, GitMerge, Terminal
} from "lucide-react";

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
  return (
    <aside className="w-60 bg-dark-800 border-r border-white/5 flex flex-col shrink-0">
      <div className="px-6 py-5 border-b border-white/5">
        <span className="text-brand-500 font-bold text-xl tracking-tight">Sentinelle</span>
        <p className="text-xs text-gray-500 mt-0.5">Community Intelligence</p>
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
      </div>
    </aside>
  );
}
