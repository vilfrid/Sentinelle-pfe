import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCampaigns, matchInfluencers } from "../services/api";
import { Users, Star, Target } from "lucide-react";

type MatchResult = {
  influencer: { id: number; username: string; display_name?: string; follower_count: number; avg_engagement_rate: number; content_topics: string[]; dominant_language?: string };
  match_score: number; matching_topics: string[]; reasoning: string;
};

export default function Matching() {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const { data: matches = [], isLoading, refetch } = useQuery({
    queryKey: ["matches", campaignId],
    queryFn: () => matchInfluencers(campaignId!, 10),
    enabled: false,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Brand-Influencer Matching</h1>
        <p className="text-gray-400 text-sm">Vector similarity matching between campaign keywords and influencer profiles</p>
      </div>

      <div className="flex gap-4 items-end">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Campaign</label>
          <select value={campaignId ?? ""} onChange={(e) => setCampaignId(e.target.value ? parseInt(e.target.value) : null)}
            className="bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
            <option value="">Select campaign</option>
            {campaigns.map((c: { id: number; name: string; brand: string }) => (
              <option key={c.id} value={c.id}>{c.name} ({c.brand})</option>
            ))}
          </select>
        </div>
        <button onClick={() => refetch()} disabled={!campaignId}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
          <Target size={14} /> Find Matches
        </button>
      </div>

      {isLoading && <div className="text-gray-400 text-sm">Computing matches...</div>}

      {matches.length > 0 && (
        <div className="grid gap-4">
          {matches.map((m: MatchResult, i: number) => (
            <div key={m.influencer.id} className="card flex items-start gap-4">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-brand-600/20 text-brand-400 font-bold text-sm shrink-0">
                #{i + 1}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h3 className="font-semibold">@{m.influencer.username}</h3>
                  {m.influencer.display_name && (
                    <span className="text-sm text-gray-400">{m.influencer.display_name}</span>
                  )}
                  {m.influencer.dominant_language && (
                    <span className="text-xs bg-dark-700 text-gray-400 px-2 py-0.5 rounded-full">{m.influencer.dominant_language}</span>
                  )}
                </div>
                <div className="flex gap-4 mt-1 text-xs text-gray-400">
                  <span><Users size={10} className="inline mr-1" />{m.influencer.follower_count.toLocaleString()} followers</span>
                  <span><Star size={10} className="inline mr-1" />{(m.influencer.avg_engagement_rate * 100).toFixed(1)}% engagement</span>
                </div>
                {m.matching_topics.length > 0 && (
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {m.matching_topics.map((t) => (
                      <span key={t} className="bg-green-500/20 text-green-400 text-xs px-2 py-0.5 rounded-full">{t}</span>
                    ))}
                  </div>
                )}
                <p className="text-xs text-gray-500 mt-1">{m.reasoning}</p>
              </div>
              <div className="text-right shrink-0">
                <div className="text-2xl font-bold text-brand-400">{(m.match_score * 100).toFixed(0)}%</div>
                <div className="text-xs text-gray-500">match</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && matches.length === 0 && campaignId && (
        <div className="card text-gray-400 text-sm">
          No influencer profiles in database yet. Add influencers via the API to enable matching.
        </div>
      )}
    </div>
  );
}
