import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCampaigns, getMetrics, computeMetrics, getSentimentTimeline, getTopics } from "../services/api";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { format } from "date-fns";

export default function Analytics() {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [period, setPeriod] = useState("weekly");
  const qc = useQueryClient();

  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });
  const { data: metrics = [] } = useQuery({
    queryKey: ["metrics", campaignId],
    queryFn: () => getMetrics(campaignId!),
    enabled: !!campaignId,
  });
  const { data: timeline = [] } = useQuery({
    queryKey: ["timeline", campaignId],
    queryFn: () => getSentimentTimeline(campaignId!),
    enabled: !!campaignId,
  });
  const { data: topics } = useQuery({
    queryKey: ["topics", campaignId],
    queryFn: () => getTopics(campaignId!),
    enabled: !!campaignId,
  });

  const compute = useMutation({
    mutationFn: () => computeMetrics(campaignId!, period),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["metrics", campaignId] }),
  });

  const chartData = timeline.map((t: { date: string; positive: number; negative: number; neutral: number }) => ({
    date: format(new Date(t.date), "MMM d"),
    positive: t.positive,
    negative: t.negative,
    neutral: t.neutral,
  }));

  const latest = metrics[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Analytics</h1>
        <p className="text-gray-400 text-sm">Deep metrics per campaign</p>
      </div>

      <div className="flex gap-4 items-end">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Campaign</label>
          <select value={campaignId ?? ""} onChange={(e) => setCampaignId(e.target.value ? parseInt(e.target.value) : null)}
            className="bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
            <option value="">Select campaign</option>
            {campaigns.map((c: { id: number; name: string }) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Period</label>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}
            className="bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
            {["daily", "weekly", "monthly"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <button onClick={() => compute.mutate()} disabled={!campaignId}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
          Compute Metrics
        </button>
      </div>

      {latest && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            {
              label: "Impression Score",
              value: latest.impression_score?.toLocaleString() ?? "—",
              sub: latest.engagement_rate === 0 ? "estimated (no views)" : undefined,
            },
            {
              label: "Engagement Rate",
              value: latest.engagement_rate > 0
                ? `${(latest.engagement_rate * 100).toFixed(2)}%`
                : "N/A",
              sub: latest.engagement_rate === 0 ? "no view data" : undefined,
            },
            {
              label: "Virality Score",
              value: latest.virality_score > 0 ? latest.virality_score.toFixed(4) : "—",
              sub: latest.virality_score === 0 ? "no shares captured" : undefined,
            },
            { label: "Audience Mood", value: latest.audience_mood },
          ].map(({ label, value, sub }) => (
            <div key={label} className="card">
              <p className="text-xs text-gray-400">{label}</p>
              <p className="text-xl font-bold mt-1 capitalize">{value}</p>
              {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
            </div>
          ))}
        </div>
      )}

      {chartData.length > 0 && (
        <div className="card">
          <h2 className="font-semibold mb-4">Sentiment Timeline</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
              <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
              <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
              <Tooltip contentStyle={{ background: "#1c2030", border: "1px solid #ffffff10" }} />
              <Area type="monotone" dataKey="positive" stackId="1" stroke="#22c55e" fill="#22c55e40" />
              <Area type="monotone" dataKey="neutral" stackId="1" stroke="#6b7280" fill="#6b728040" />
              <Area type="monotone" dataKey="negative" stackId="1" stroke="#ef4444" fill="#ef444440" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {topics && topics.topics?.length > 0 && (
        <div className="card">
          <h2 className="font-semibold mb-4">Trending Topics</h2>
          <div className="flex flex-wrap gap-2">
            {topics.topics.slice(0, 30).map((t: { topic: string; count: number }) => (
              <span key={t.topic} className="bg-brand-600/20 text-brand-300 text-sm px-3 py-1 rounded-full">
                {t.topic} <span className="text-brand-500 text-xs">({t.count})</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
