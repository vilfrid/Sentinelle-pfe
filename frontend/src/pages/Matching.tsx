import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCampaigns, matchCreators, computeEmbeddings, updateCreator } from "../services/api";
import { Users, Star, Target, Cpu, Sparkles, MessageSquare } from "lucide-react";

type MatchCreator = {
  id: number; username: string; display_name?: string; bio?: string;
  profile_url?: string; follower_count: number; total_comments: number;
  positive_pct: number; negative_pct: number; audience_mood?: string;
  content_topics: string[]; has_embedding: boolean; campaign_id: number | null;
};

type MatchResult = {
  creator: MatchCreator;
  match_score: number; matching_topics: string[]; method: string; reasoning: string;
};

export default function Matching() {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const qc = useQueryClient();
  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const { data: matches = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["matches", campaignId],
    queryFn: () => matchCreators(campaignId!, 10),
    enabled: false,
  });

  const embedMutation = useMutation({
    mutationFn: computeEmbeddings,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      alert(`Embeddings computed: ${data.campaigns_updated} campaigns, ${data.creators_updated} creators updated`);
    },
  });

  const linkMutation = useMutation({
    mutationFn: ({ creatorId, campaignId }: { creatorId: number; campaignId: number }) => updateCreator(creatorId, { campaign_id: campaignId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      qc.invalidateQueries({ queryKey: ["creators"] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Brand-Creator Matching</h1>
        <p className="text-gray-400 text-sm">AI-powered semantic matching using Google text-embedding-004 vectors</p>
      </div>

      <div className="flex gap-4 items-end flex-wrap">
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
        <button onClick={() => embedMutation.mutate()} disabled={embedMutation.isPending}
          className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
          <Sparkles size={14} />
          {embedMutation.isPending ? "Computing..." : "Compute Embeddings"}
        </button>
      </div>

      {isLoading && <div className="text-gray-400 text-sm">Computing matches...</div>}
      {isError && <div className="text-red-400 text-sm">Matching failed. Check backend logs.</div>}

      {matches.length > 0 && (
        <div className="grid gap-4">
          {matches.map((m: MatchResult, i: number) => (
            <div key={m.creator.id} className="card flex items-start gap-4">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-brand-600/20 text-brand-400 font-bold text-sm shrink-0">
                #{i + 1}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-3 flex-wrap">
                  <h3 className="font-semibold">@{m.creator.username}</h3>
                  {m.creator.display_name && (
                    <span className="text-sm text-gray-400">{m.creator.display_name}</span>
                  )}
                  {m.creator.campaign_id === null && (
                    <span className="text-xs bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded-full">Global Pool</span>
                  )}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    m.method === "embedding"
                      ? "bg-purple-500/20 text-purple-400"
                      : "bg-gray-500/20 text-gray-400"
                  }`}>
                    <Cpu size={9} className="inline mr-1" />
                    {m.method}
                  </span>
                  {m.creator.has_embedding && (
                    <span className="text-xs bg-green-500/10 text-green-400 px-2 py-0.5 rounded-full">
                      embedded
                    </span>
                  )}
                </div>
                <div className="flex gap-4 mt-1 text-xs text-gray-400 flex-wrap">
                  <span><MessageSquare size={10} className="inline mr-1" />{m.creator.total_comments.toLocaleString()} comments</span>
                  {m.creator.audience_mood && (
                    <span className="capitalize">mood: {m.creator.audience_mood}</span>
                  )}
                  <span className="text-green-400">{m.creator.positive_pct}% positive</span>
                  <span className="text-red-400">{m.creator.negative_pct}% negative</span>
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
                <div className="text-xs text-gray-500 mb-2">match</div>
                {m.creator.campaign_id === null && campaignId && (
                  <button 
                    onClick={() => linkMutation.mutate({ creatorId: m.creator.id, campaignId })}
                    disabled={linkMutation.isPending}
                    className="text-xs bg-brand-600 hover:bg-brand-700 text-white px-2 py-1 rounded transition-colors"
                  >
                    Add to Campaign
                  </button>
                )}
                {m.creator.campaign_id === campaignId && (
                   <div className="text-xs text-green-400">In Campaign</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && matches.length === 0 && campaignId && (
        <div className="card text-gray-400 text-sm">
          No creators found. Add creators and run the pipeline first, then compute embeddings for better matching.
        </div>
      )}
    </div>
  );
}
