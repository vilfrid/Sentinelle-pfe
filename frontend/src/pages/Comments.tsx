import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCampaigns } from "../services/api";
import axios from "axios";

type Comment = {
  id: number; author: string; raw_text: string;
  sentiment?: string; sentiment_score?: number; language?: string; likes: number;
};

const sentimentBadge = (s?: string) => {
  if (!s) return <span className="badge-neutral">—</span>;
  if (s === "positive") return <span className="badge-positive">positive</span>;
  if (s === "negative") return <span className="badge-negative">negative</span>;
  return <span className="badge-neutral">neutral</span>;
};

export default function Comments() {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [filter, setFilter] = useState("all");

  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const { data: comments = [], isLoading } = useQuery({
    queryKey: ["comments", campaignId, filter],
    queryFn: async () => {
      const params: Record<string, string | number> = {};
      if (campaignId) params.campaign_id = campaignId;
      if (filter !== "all") params.sentiment = filter;
      const r = await axios.get("/api/comments/", { params });
      return r.data;
    },
    enabled: !!campaignId,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Comments</h1>
        <p className="text-gray-400 text-sm">Browse and filter all collected comments</p>
      </div>

      <div className="flex gap-4 flex-wrap">
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
          <label className="text-xs text-gray-400 mb-1 block">Sentiment</label>
          <div className="flex gap-1">
            {["all", "positive", "negative", "neutral"].map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-2 rounded-lg text-xs font-medium capitalize transition-colors ${
                  filter === f ? "bg-brand-600 text-white" : "bg-dark-700 text-gray-400 hover:text-white"
                }`}>{f}</button>
            ))}
          </div>
        </div>
      </div>

      {!campaignId ? (
        <div className="card text-gray-400 text-sm">Select a campaign to view comments.</div>
      ) : isLoading ? (
        <div className="text-gray-400 text-sm">Loading...</div>
      ) : comments.length === 0 ? (
        <div className="card text-gray-400 text-sm">No comments found.</div>
      ) : (
        <div className="space-y-3">
          {comments.slice(0, 100).map((c: Comment) => (
            <div key={c.id} className="card">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-300">@{c.author || "unknown"}</span>
                    {sentimentBadge(c.sentiment)}
                    {c.language && (
                      <span className="text-xs bg-dark-700 text-gray-400 px-2 py-0.5 rounded-full">{c.language}</span>
                    )}
                  </div>
                  <p className="text-sm text-gray-200">{c.raw_text}</p>
                </div>
                <div className="text-right shrink-0">
                  {c.sentiment_score !== undefined && (
                    <p className={`text-sm font-bold ${
                      c.sentiment_score > 0 ? "text-green-400" :
                      c.sentiment_score < 0 ? "text-red-400" : "text-gray-400"
                    }`}>
                      {c.sentiment_score > 0 ? "+" : ""}{c.sentiment_score?.toFixed(2)}
                    </p>
                  )}
                  <p className="text-xs text-gray-500">{c.likes} likes</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
