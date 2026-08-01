import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCampaigns, matchCreators, computeEmbeddings, updateCreator, refreshAllMatches, checkEmbeddingBackend } from "../services/api";
import {
  Users, Target, Cpu, Sparkles, MessageSquare, TrendingUp,
  Eye, Heart, Hash, Shield, Clock, Zap, RefreshCw, Share2,
} from "lucide-react";
import { clsx } from "clsx";

// ── Types ──────────────────────────────────────────────────────────────────────
type ScoreBreakdown = {
  semantic: number; niche: number; audience: number; reach: number;
  brand_safety: number; recency: number;
  topic_overlap: number; hashtag_overlap: number; caption_density: number;
  bio_match: number; engagement_score: number; authenticity: number;
  comment_depth: number; virality: number;
  niche_from_semantic: boolean;
};

type MatchCreator = {
  id: number; username: string; display_name?: string; bio?: string;
  profile_url?: string; avatar_url?: string;
  follower_count: number; total_comments: number;
  positive_pct: number; negative_pct: number; neutral_pct: number;
  audience_mood?: string; content_topics: string[]; has_embedding: boolean;
  campaign_id: number | null; influencer_tier: string; platform?: string;
  post_count: number; avg_views: number; avg_likes: number; avg_shares: number;
  avg_comments_per_post: number; engagement_rate: number; share_rate: number;
  top_hashtags: string[]; authenticity_score: number; estimated_reach: number;
  content_type_mix: { video: number; photo: number; carousel: number };
};

type MatchResult = {
  creator: MatchCreator;
  match_score: number;
  score_breakdown: ScoreBreakdown;
  method: string;
  matching_topics: string[];
  matching_hashtags: string[];
  reasoning: string;
  estimated_reach: number;
  influencer_tier: string;
  platform?: string;
};

// ── Helpers ────────────────────────────────────────────────────────────────────
const fmt = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n > 0 ? n.toString() : "—";
};

const TIER_STYLES: Record<string, string> = {
  mega:    "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  macro:   "text-purple-400 bg-purple-500/10 border-purple-500/30",
  micro:   "text-blue-400   bg-blue-500/10   border-blue-500/30",
  nano:    "text-green-400  bg-green-500/10  border-green-500/30",
  unknown: "text-gray-400   bg-gray-500/10   border-gray-500/30",
};

const PLATFORM_COLORS: Record<string, string> = {
  instagram: "text-pink-400 bg-pink-500/10",
  youtube:   "text-red-400  bg-red-500/10",
};

// Progress bar for a single score component
function ScoreBar({
  label, value, icon, color = "bg-brand-500",
}: { label: string; value: number; icon?: React.ReactNode; color?: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      {icon && <span className="text-gray-500 shrink-0">{icon}</span>}
      <span className="text-xs text-gray-400 w-20 shrink-0">{label}</span>
      <div className="flex-1 bg-dark-700 rounded-full h-1.5 overflow-hidden">
        <div
          className={clsx("h-1.5 rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right shrink-0">{pct}%</span>
    </div>
  );
}

// Audience mood color
function moodColor(mood: string) {
  return { happy: "text-green-400", angry: "text-red-400", mixed: "text-yellow-400" }[mood] ?? "text-gray-400";
}

// ── Match Card ─────────────────────────────────────────────────────────────────
function MatchCard({
  m, rank, campaignId, onLink,
}: { m: MatchResult; rank: number; campaignId: number; onLink: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const c = m.creator;
  const bd = m.score_breakdown;
  const matchPct = Math.round(m.match_score * 100);
  const tierCls = TIER_STYLES[c.influencer_tier] ?? TIER_STYLES.unknown;
  const platCls = PLATFORM_COLORS[c.platform ?? ""] ?? "text-gray-400 bg-gray-500/10";

  return (
    <div className="card space-y-4">
      {/* ── Header row ── */}
      <div className="flex items-start gap-4">
        {/* Rank */}
        <div className="flex items-center justify-center w-9 h-9 rounded-full bg-brand-600/20 text-brand-400 font-bold text-sm shrink-0 mt-0.5">
          #{rank}
        </div>

        {/* Avatar */}
        {c.avatar_url ? (
          <img
            src={c.avatar_url.startsWith("/")
              ? c.avatar_url
              : `/api/proxy/image?url=${encodeURIComponent(c.avatar_url)}`}
            alt={c.username}
            className="w-12 h-12 rounded-full object-cover shrink-0 border border-white/10" />
        ) : (
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-brand-600/40 to-purple-600/40 flex items-center justify-center text-white font-bold text-lg shrink-0 border border-white/10">
            {c.username[0]?.toUpperCase()}
          </div>
        )}

        {/* Meta */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-base">@{c.username}</h3>
            {c.display_name && (
              <span className="text-sm text-gray-500">{c.display_name}</span>
            )}
            {/* Tier badge */}
            <span className={clsx("text-xs px-2 py-0.5 rounded-full border font-medium capitalize", tierCls)}>
              {c.influencer_tier}
            </span>
            {/* Platform badge */}
            {c.platform && (
              <span className={clsx("text-xs px-2 py-0.5 rounded-full capitalize font-medium", platCls)}>
                {c.platform}
              </span>
            )}
            {/* Method badge */}
            <span className={clsx("text-xs px-2 py-0.5 rounded-full flex items-center gap-1", {
              "bg-purple-500/20 text-purple-400": m.method === "embedding",
              "bg-gray-500/20 text-gray-400":    m.method !== "embedding",
            })}>
              <Cpu size={9} />{m.method}
            </span>
            {c.has_embedding && (
              <span className="text-xs bg-green-500/10 text-green-400 px-2 py-0.5 rounded-full">embedded</span>
            )}
            {c.campaign_id === null && (
              <span className="text-xs bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded-full">Global Pool</span>
            )}
          </div>

          {/* Stats row */}
          <div className="flex gap-4 mt-1.5 text-xs text-gray-400 flex-wrap">
            {c.follower_count > 0 && (
              <span className="flex items-center gap-1">
                <Users size={10} /> {fmt(c.follower_count)} followers
              </span>
            )}
            <span className="flex items-center gap-1">
              <MessageSquare size={10} /> {c.total_comments.toLocaleString()} comments
            </span>
            {c.avg_views > 0 && (
              <span className="flex items-center gap-1">
                <Eye size={10} /> {fmt(c.avg_views)} avg views
              </span>
            )}
            {c.avg_likes > 0 && (
              <span className="flex items-center gap-1">
                <Heart size={10} /> {fmt(c.avg_likes)} avg likes
              </span>
            )}
            {c.avg_shares > 0 && (
              <span className="flex items-center gap-1 text-orange-400">
                <Share2 size={10} /> {fmt(c.avg_shares)} avg reposts
              </span>
            )}
            {c.engagement_rate > 0 && (
              <span className="flex items-center gap-1 text-brand-400">
                <TrendingUp size={10} /> {c.engagement_rate}% eng
              </span>
            )}
            {c.post_count > 0 && (
              <span>{c.post_count} posts</span>
            )}
            {/* Content type mix pill */}
            {c.content_type_mix && c.content_type_mix.video >= 50 && (
              <span className="text-purple-400">🎬 {c.content_type_mix.video}% video</span>
            )}
          </div>

          {/* Audience mood + sentiment */}
          {(c.audience_mood || c.positive_pct > 0) && (
            <div className="flex gap-3 mt-1 text-xs flex-wrap">
              {c.audience_mood && (
                <span className={clsx("capitalize font-medium", moodColor(c.audience_mood))}>
                  {c.audience_mood} mood
                </span>
              )}
              {c.positive_pct > 0 && (
                <span className="text-green-400">{c.positive_pct}% positive</span>
              )}
              {c.negative_pct > 0 && (
                <span className="text-red-400">{c.negative_pct}% negative</span>
              )}
              {c.authenticity_score >= 0.85 && (
                <span className="text-cyan-400 flex items-center gap-1">
                  <Shield size={9} /> Authentic
                </span>
              )}
            </div>
          )}
        </div>

        {/* Score + CTA */}
        <div className="text-right shrink-0 space-y-2">
          <div>
            <div className="text-3xl font-bold text-brand-400 leading-none">{matchPct}%</div>
            <div className="text-xs text-gray-500">match score</div>
          </div>
          {c.estimated_reach > 0 && (
            <div className="text-xs text-gray-400">
              <Zap size={9} className="inline mr-1 text-yellow-400" />
              {fmt(c.estimated_reach)} reach
            </div>
          )}
          {c.campaign_id === null && (
            <button
              onClick={onLink}
              className="text-xs bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded-lg transition-colors"
            >
              Add to Campaign
            </button>
          )}
          {c.campaign_id === campaignId && (
            <div className="text-xs text-green-400">In Campaign</div>
          )}
        </div>
      </div>

      {/* ── Score breakdown ── */}
      <div className="bg-dark-700/50 rounded-xl p-3 space-y-1.5">
        <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wide">Score Breakdown</div>
        <ScoreBar label="Semantic"    value={bd.semantic}     icon={<Cpu size={10} />}          color="bg-purple-500" />
        <div>
          <ScoreBar label="Content Fit" value={bd.niche}      icon={<Target size={10} />}        color="bg-brand-500" />
          {bd.niche_from_semantic && (bd.topic_overlap === 0 && bd.hashtag_overlap === 0 && bd.caption_density === 0 && bd.bio_match === 0) && (
            <p className="text-xs text-purple-400/70 ml-6 mt-0.5">↑ AI similarity match (no keyword overlap found)</p>
          )}
        </div>
        <ScoreBar label="Audience"    value={bd.audience}     icon={<Users size={10} />}         color="bg-cyan-500" />
        <ScoreBar label="Reach"       value={bd.reach}        icon={<Eye size={10} />}           color="bg-yellow-500" />
        <ScoreBar label="Brand Safety" value={bd.brand_safety} icon={<Shield size={10} />}       color="bg-green-500" />
        <ScoreBar label="Recency"     value={bd.recency}      icon={<Clock size={10} />}         color="bg-orange-500" />

        {/* Sub-score details toggle */}
        {(bd.topic_overlap > 0 || bd.hashtag_overlap > 0 || bd.caption_density > 0 || bd.bio_match > 0 || bd.virality > 0) && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-gray-600 hover:text-gray-400 mt-1 transition-colors"
          >
            {expanded ? "▲ hide" : "▼ signal details"}
          </button>
        )}
        {expanded && (
          <div className="pt-1 pl-4 space-y-1 border-l border-white/5">
            <div className="text-xs text-gray-600 mb-1">Content fit sub-scores</div>
            {bd.topic_overlap > 0 && <ScoreBar label="Topics"    value={bd.topic_overlap}   color="bg-brand-600/70" />}
            {bd.hashtag_overlap > 0 && <ScoreBar label="Hashtags"  value={bd.hashtag_overlap} color="bg-brand-600/70" />}
            {bd.caption_density > 0 && <ScoreBar label="Captions"  value={bd.caption_density} color="bg-brand-600/70" />}
            {bd.bio_match > 0 && <ScoreBar label="Bio match"  value={bd.bio_match}       color="bg-indigo-500/70" />}
            <div className="text-xs text-gray-600 mt-2 mb-1">Audience sub-scores</div>
            {bd.engagement_score > 0 && <ScoreBar label="Eng. rate" value={bd.engagement_score} color="bg-cyan-600/70" />}
            {bd.authenticity > 0 && <ScoreBar label="Auth."     value={bd.authenticity}    color="bg-cyan-600/70" />}
            {bd.virality > 0 && <ScoreBar label="Virality"  value={bd.virality}        color="bg-orange-500/70" />}
          </div>
        )}
      </div>

      {/* ── Topics + hashtags ── */}
      {(m.matching_topics.length > 0 || m.matching_hashtags.length > 0 || c.top_hashtags.length > 0) && (
        <div className="flex gap-1 flex-wrap">
          {m.matching_topics.map((t) => (
            <span key={t} className="bg-green-500/20 text-green-400 text-xs px-2 py-0.5 rounded-full border border-green-500/20">
              {t}
            </span>
          ))}
          {m.matching_hashtags.map((t) => (
            <span key={t} className="bg-brand-500/20 text-brand-400 text-xs px-2 py-0.5 rounded-full border border-brand-500/20">
              <Hash size={8} className="inline" />{t}
            </span>
          ))}
          {/* Non-matching hashtags (dimmed) */}
          {c.top_hashtags
            .filter((h) => !m.matching_hashtags.includes(h))
            .slice(0, 6)
            .map((h) => (
              <span key={h} className="bg-dark-700 text-gray-500 text-xs px-2 py-0.5 rounded-full">
                #{h}
              </span>
            ))}
        </div>
      )}

      {/* ── Content topics ── */}
      {c.content_topics.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {c.content_topics.slice(0, 8).map((t) => (
            <span key={t} className="bg-dark-700 text-gray-400 text-xs px-2 py-0.5 rounded-full">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* ── Reasoning ── */}
      <p className="text-xs text-gray-500 leading-relaxed">{m.reasoning}</p>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function Matching() {
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [topK, setTopK] = useState(10);
  const qc = useQueryClient();

  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const { data: matches = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["matches", campaignId, topK],
    queryFn: () => matchCreators(campaignId!, topK),
    enabled: false,
  });

  const { data: embedBackend } = useQuery({
    queryKey: ["embed-backend"],
    queryFn: checkEmbeddingBackend,
    staleTime: 60_000,
  });

  const embedMutation = useMutation({
    mutationFn: ({ force }: { force: boolean }) => computeEmbeddings(force),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      const backend = data.backend ?? "unknown";
      const dim = data.dim ?? "?";
      alert(
        `Embeddings computed (${backend}, ${dim}-dim):\n` +
        `${data.campaigns_updated} campaigns · ${data.creators_updated} creators updated` +
        (data.errors?.length ? `\n\nErrors:\n${data.errors.join("\n")}` : "")
      );
    },
  });

  const refreshAllMutation = useMutation({
    mutationFn: refreshAllMatches,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      if (campaignId) refetch();
      alert(`Cache refreshed for ${data.refreshed} campaign(s).`);
    },
    onError: () => alert("Refresh failed — check that Redis and the backend are running."),
  });

  const linkMutation = useMutation({
    mutationFn: ({ creatorId, campId }: { creatorId: number; campId: number }) =>
      updateCreator(creatorId, { campaign_id: campId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      qc.invalidateQueries({ queryKey: ["creators"] });
    },
  });

  const typedMatches = matches as MatchResult[];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Brand-Creator Matching</h1>
        <p className="text-gray-400 text-sm">
          Multi-signal AI matching: semantic embedding · content fit · audience quality · reach · brand safety · recency
        </p>
      </div>

      {/* Controls */}
      <div className="flex gap-3 items-end flex-wrap">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Campaign</label>
          <select
            value={campaignId ?? ""}
            onChange={(e) => setCampaignId(e.target.value ? parseInt(e.target.value) : null)}
            className="bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none"
          >
            <option value="">Select campaign</option>
            {campaigns.map((c: { id: number; name: string; brand: string }) => (
              <option key={c.id} value={c.id}>{c.name} — {c.brand}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Top K</label>
          <select
            value={topK}
            onChange={(e) => setTopK(parseInt(e.target.value))}
            className="bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none"
          >
            {[5, 10, 20, 30].map((k) => (
              <option key={k} value={k}>Top {k}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => refetch()}
          disabled={!campaignId || isLoading}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          <Target size={14} />
          {isLoading ? "Computing…" : "Find Matches"}
        </button>
        <div className="flex flex-col gap-1">
          <div className="flex gap-2">
            <button
              onClick={() => embedMutation.mutate({ force: false })}
              disabled={embedMutation.isPending}
              className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              <Sparkles size={14} />
              {embedMutation.isPending ? "Embedding…" : "Compute Embeddings"}
            </button>
            <button
              onClick={() => embedMutation.mutate({ force: true })}
              disabled={embedMutation.isPending}
              title="Clear and regenerate all embeddings (use when switching model)"
              className="flex items-center gap-2 bg-purple-900/60 hover:bg-purple-800/60 border border-purple-500/30 disabled:opacity-50 text-purple-300 px-3 py-2 rounded-lg text-sm font-medium"
            >
              ↺ Force
            </button>
          </div>
          {embedBackend && (
            <span className="text-xs text-gray-500 pl-1">
              Backend: <span className={embedBackend.bge_ready ? "text-green-400" : embedBackend.bge_url ? "text-yellow-400" : "text-red-400"}>
                {embedBackend.bge_ready ? "BGE-M3 (1024-dim)" : embedBackend.bge_url ? "BGE-M3 (sleeping — click Compute)" : "not configured"}
              </span>
            </span>
          )}
        </div>
        <button
          onClick={() => refreshAllMutation.mutate()}
          disabled={refreshAllMutation.isPending}
          className="flex items-center gap-2 bg-dark-700 hover:bg-dark-600 border border-white/10 text-gray-300 px-4 py-2 rounded-lg text-sm font-medium"
        >
          <RefreshCw size={14} className={refreshAllMutation.isPending ? "animate-spin" : ""} />
          Refresh Cache
        </button>
      </div>

      {/* Legend */}
      <div className="flex gap-4 flex-wrap text-xs text-gray-500">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500 inline-block" /> Semantic (32%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-brand-500 inline-block" /> Content Fit (20%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-cyan-500 inline-block" /> Audience (20%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-500 inline-block" /> Reach (13%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block" /> Brand Safety (10%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block" /> Recency (5%)</span>
      </div>

      {isError && (
        <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
          Matching failed. Check that the backend is running.
        </div>
      )}

      {/* Results */}
      {typedMatches.length > 0 ? (
        <div className="space-y-4">
          <p className="text-xs text-gray-500">{typedMatches.length} creators ranked by composite match score</p>
          {typedMatches.map((m, i) => (
            <MatchCard
              key={m.creator.id}
              m={m}
              rank={i + 1}
              campaignId={campaignId!}
              onLink={() => campaignId && linkMutation.mutate({ creatorId: m.creator.id, campId: campaignId })}
            />
          ))}
        </div>
      ) : !isLoading && campaignId ? (
        <div className="card text-center py-12 text-gray-400 text-sm">
          No creators matched. Add creators and run their pipeline first,
          then click <strong>Compute Embeddings</strong> for semantic matching.
        </div>
      ) : null}
    </div>
  );
}
