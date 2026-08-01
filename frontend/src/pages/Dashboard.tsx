import { useQuery } from "@tanstack/react-query";
import { getOverview } from "../services/api";
import { MessageSquare, Megaphone, TrendingUp, AlertTriangle } from "lucide-react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { useChartTheme } from "../contexts/ThemeContext";

const COLORS = { positive: "#22c55e", negative: "#ef4444", neutral: "#6b7280" };

const RADIAN = Math.PI / 180;
function renderSliceLabel({ cx, cy, midAngle, innerRadius, outerRadius, value, percent }: {
  cx: number; cy: number; midAngle: number; innerRadius: number; outerRadius: number; value: number; percent: number;
}) {
  if (percent < 0.04) return null;
  const r = (innerRadius + outerRadius) / 2;
  const x = cx + r * Math.cos(-midAngle * RADIAN);
  const y = cy + r * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={13} fontWeight={600}>
      {value.toLocaleString()}
    </text>
  );
}

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number; icon: React.ElementType; color: string }) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`p-3 rounded-lg ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <p className="text-2xl font-bold">{value.toLocaleString()}</p>
        <p className="text-sm text-gray-400">{label}</p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data, isLoading } = useQuery({ queryKey: ["overview"], queryFn: getOverview });
  const chart = useChartTheme();

  if (isLoading) return <div className="text-gray-400 text-sm">Loading dashboard...</div>;

  const sentimentData = data
    ? [
        { name: "Positive", value: data.sentiment_breakdown.positive },
        { name: "Negative", value: data.sentiment_breakdown.negative },
        { name: "Neutral", value: data.sentiment_breakdown.neutral },
      ]
    : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">Real-time community intelligence overview</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Campaigns" value={data?.total_campaigns ?? 0} icon={Megaphone} color="bg-brand-600/20 text-brand-400" />
        <StatCard label="Total Comments" value={data?.total_comments ?? 0} icon={MessageSquare} color="bg-purple-500/20 text-purple-400" />
        <StatCard label="Analyzed" value={data?.analyzed_comments ?? 0} icon={TrendingUp} color="bg-green-500/20 text-green-400" />
        <StatCard label="Spike Alerts" value={data?.negative_spike_alerts?.length ?? 0} icon={AlertTriangle} color="bg-red-500/20 text-red-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sentiment pie */}
        <div className="card">
          <h2 className="text-base font-semibold mb-4">Sentiment Breakdown</h2>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={sentimentData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} dataKey="value" label={renderSliceLabel} labelLine={false}>
                {sentimentData.map((entry) => (
                  <Cell key={entry.name} fill={COLORS[entry.name.toLowerCase() as keyof typeof COLORS]} />
                ))}
              </Pie>
              <Tooltip formatter={(v: number) => v.toLocaleString()} contentStyle={chart.tooltip} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Negative spike alerts */}
        <div className="card">
          <h2 className="text-base font-semibold mb-4">Negative Spike Alerts</h2>
          {data?.negative_spike_alerts?.length === 0 ? (
            <p className="text-gray-500 text-sm">No alerts detected.</p>
          ) : (
            <div className="space-y-3">
              {data?.negative_spike_alerts?.map((alert: { campaign_id: number; period: string; negative_pct: number; detected_at: string }, i: number) => (
                <div key={i} className="flex items-center justify-between bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-red-300">Campaign #{alert.campaign_id}</p>
                    <p className="text-xs text-gray-400">{alert.period} · {new Date(alert.detected_at).toLocaleDateString()}</p>
                  </div>
                  <span className="text-red-400 font-bold text-sm">{alert.negative_pct}% negative</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
