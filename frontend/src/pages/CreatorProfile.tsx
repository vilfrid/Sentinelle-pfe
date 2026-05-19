import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCreator, getCreatorPosts, getCreatorComments, getTopComments, refreshCreator, stopCreator } from "../services/api";
import {
  RefreshCw, ArrowLeft, MessageSquare, Loader, Heart,
  CheckCircle, AlertCircle, ExternalLink, Square, Users, Star
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid
} from "recharts";
import { clsx } from "clsx";

const SENTIMENT_COLORS = { positive: "#22c55e", negative: "#ef4444", neutral: "#6b7280" };

type Post    = { id: number; url: string; external_id: string; likes: number; views: number; comment_count: number; etl_status: string; scraped_at: string };
type Comment = { id: number; author: string; raw_text: string; sentiment?: string; sentiment_score?: number; language?: string; likes: number; posted_at?: string };
type TopComment = { id: number; author: string; text: string; likes: number; sentiment?: string; sentiment_score?: number; posted_at?: string };

const fmtFollowers = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n > 0 ? n.toString() : null;
};
const getTier = (n: number) => {
  if (n >= 1_000_000) return { label: "Mega",  cls: "text-yellow-400 bg-yellow-500/10" };
  if (n >= 100_000)   return { label: "Macro", cls: "text-purple-400 bg-purple-500/10" };
  if (n >= 10_000)    return { label: "Micro", cls: "text-blue-400 bg-blue-500/10" };
  if (n > 0)          return { label: "Nano",  cls: "text-green-400 bg-green-500/10" };
  return null;
};

const statusColor = (s: string) =>
  ({ analyzed: "text-green-400", transformed: "text-blue-400", scraped: "text-yellow-400", pending: "text-gray-400", scrape_failed: "text-red-400", etl_failed: "text-red-400" }[s] ?? "text-gray-400");

export default function CreatorProfile() {
  const { id } = useParams<{ id: string }>();
  const creatorId = parseInt(id!);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [sentFilter, setSentFilter] = useState("all");
  const [commentSort, setCommentSort] = useState<"date" | "likes">("date");
  const [activeTab, setActiveTab] = useState<"overview" | "posts" | "comments">("overview");

  const { data: creator, isLoading } = useQuery({
    queryKey: ["creator", creatorId],
    queryFn: () => getCreator(creatorId),
    refetchInterval: (query) => {
      const data = query.state.data as { status: string } | undefined;
      return data && ["discovering", "scraping", "processing"].includes(data.status) ? 3000 : false;
    },
  });

  const { data: posts = [] } = useQuery({
    queryKey: ["creator-posts", creatorId],
    queryFn: () => getCreatorPosts(creatorId),
    enabled: activeTab === "posts",
  });

  const { data: comments = [] } = useQuery({
    queryKey: ["creator-comments", creatorId, sentFilter, commentSort],
    queryFn: () => getCreatorComments(creatorId, sentFilter === "all" ? undefined : sentFilter, commentSort),
    enabled: activeTab === "comments",
  });

  const { data: topComments = [] } = useQuery({
    queryKey: ["top-comments", creatorId],
    queryFn: () => getTopComments(creatorId),
    enabled: activeTab === "overview" && creator?.status === "done",
  });

  const refresh = useMutation({
    mutationFn: () => refreshCreator(creatorId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["creator", creatorId] }),
  });

  const stop = useMutation({
    mutationFn: () => stopCreator(creatorId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["creator", creatorId] }),
  });

  if (isLoading) return <div className="text-gray-400 text-sm">Loading...</div>;
  if (!creator) return <div className="text-red-400 text-sm">Creator not found.</div>;

  const isRunning = ["discovering","scraping","processing"].includes(creator.status);

  const pieData = [
    { name: "Positive", value: creator.positive_pct },
    { name: "Negative", value: creator.negative_pct },
    { name: "Neutral",  value: creator.neutral_pct },
  ];

  const topTopics = (creator.top_topics ?? []).slice(0, 10).map((t: { topic: string; count: number }) => ({
    topic: t.topic.length > 12 ? t.topic.slice(0, 12) + "…" : t.topic,
    count: t.count,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button onClick={() => navigate("/creators")} className="mt-1 text-gray-500 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            {creator.avatar_url ? (
              <img src={creator.avatar_url} alt={creator.username}
                className="w-14 h-14 rounded-full object-cover border border-white/10 shrink-0" />
            ) : (
              <div className="w-14 h-14 rounded-full bg-brand-600/20 flex items-center justify-center text-brand-400 font-bold text-2xl">
                {creator.username[0]?.toUpperCase()}
              </div>
            )}
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-bold">@{creator.username}</h1>
                {(() => { const t = getTier(creator.follower_count); return t ? (
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${t.cls}`}>{t.label}</span>
                ) : null; })()}
              </div>
              {creator.display_name && <p className="text-gray-400 text-sm">{creator.display_name}</p>}
              {creator.follower_count > 0 && (
                <p className="text-xs text-gray-500 flex items-center gap-1 mt-0.5">
                  <Users size={10} /> {fmtFollowers(creator.follower_count)} followers
                </p>
              )}
            </div>
            <span className={clsx("flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium", {
              "bg-green-500/10 text-green-400": creator.status === "done",
              "bg-blue-500/10 text-blue-400": creator.status === "discovering",
              "bg-yellow-500/10 text-yellow-400": creator.status === "scraping",
              "bg-purple-500/10 text-purple-400": creator.status === "processing",
              "bg-red-500/10 text-red-400": creator.status === "error",
              "bg-gray-500/10 text-gray-400": creator.status === "idle",
            })}>
              {isRunning && <Loader size={10} className="animate-spin" />}
              {creator.status === "done" && <CheckCircle size={10} />}
              {creator.status === "error" && <AlertCircle size={10} />}
              {creator.status}
            </span>
          </div>
          {creator.profile_url && (
            <a href={creator.profile_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-brand-400 hover:underline mt-1">
              <ExternalLink size={11} /> View profile
            </a>
          )}
        </div>
        {isRunning ? (
          <button onClick={() => stop.mutate()} disabled={stop.isPending}
            className="flex items-center gap-2 bg-yellow-500/10 hover:bg-yellow-500/20 disabled:opacity-50 border border-yellow-500/30 text-yellow-400 px-4 py-2 rounded-lg text-sm transition-colors">
            <Square size={14} />
            Stop Pipeline
          </button>
        ) : (
          <button onClick={() => refresh.mutate()} disabled={refresh.isPending}
            className="flex items-center gap-2 bg-dark-700 hover:bg-dark-600 disabled:opacity-50 border border-white/10 text-gray-300 px-4 py-2 rounded-lg text-sm transition-colors">
            <RefreshCw size={14} className={refresh.isPending ? "animate-spin" : ""} />
            Re-run Pipeline
          </button>
        )}
      </div>

      {isRunning && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3 text-sm text-blue-300 flex items-center gap-2">
          <Loader size={14} className="animate-spin shrink-0" />
          Pipeline running — discovering posts, scraping comments, arabizing text and running sentiment analysis…
        </div>
      )}

      {creator.status === "error" && creator.error_message && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3 text-sm text-red-300">
          {creator.error_message}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Followers",      value: fmtFollowers(creator.follower_count) ?? creator.total_posts_scraped + " posts" },
          { label: "Total comments", value: creator.total_comments.toLocaleString() },
          { label: "Positive",       value: `${creator.positive_pct}%`, color: "text-green-400" },
          { label: "Negative",       value: `${creator.negative_pct}%`, color: "text-red-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="card">
            <p className="text-xs text-gray-400">{label}</p>
            <p className={clsx("text-2xl font-bold mt-1", color ?? "text-white")}>{value}</p>
          </div>
        ))}
      </div>

      {/* Bio */}
      {creator.bio && (
        <div className="card">
          <p className="text-xs text-gray-500 mb-1">Bio</p>
          <p className="text-sm text-gray-300">{creator.bio}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-white/5">
        {(["overview", "posts", "comments"] as const).map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={clsx("px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px", {
              "border-brand-500 text-brand-400": activeTab === tab,
              "border-transparent text-gray-400 hover:text-white": activeTab !== tab,
            })}>{tab}</button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <>
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="card">
            <h2 className="font-semibold mb-4">Sentiment Distribution</h2>
            {creator.total_comments > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={90} dataKey="value" label={({ name, value }) => `${name}: ${value}%`}>
                    {pieData.map((entry) => (
                      <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name.toLowerCase() as keyof typeof SENTIMENT_COLORS]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: number) => `${v}%`} contentStyle={{ background: "#1c2030", border: "1px solid #ffffff10" }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm">No data yet.</p>
            )}
          </div>

          <div className="card">
            <h2 className="font-semibold mb-4">Trending Topics</h2>
            {topTopics.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={topTopics} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff08" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 11 }} />
                  <YAxis type="category" dataKey="topic" width={80} tick={{ fill: "#9ca3af", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#1c2030", border: "1px solid #ffffff10" }} />
                  <Bar dataKey="count" fill="#4f7df3" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm">No topics yet.</p>
            )}
          </div>

          {creator.audience_mood && (
            <div className="card lg:col-span-2">
              <p className="text-sm text-gray-400">Audience mood</p>
              <p className="text-3xl font-bold capitalize mt-1 text-brand-400">{creator.audience_mood}</p>
              <p className="text-xs text-gray-500 mt-1">avg sentiment score: {creator.avg_sentiment_score?.toFixed(3)}</p>
            </div>
          )}
        </div>

        {/* Top comments by likes */}
        {(topComments as TopComment[]).length > 0 && (
          <div className="card">
            <h2 className="font-semibold mb-3 flex items-center gap-2">
              <Star size={14} className="text-yellow-400" /> Top Comments by Likes
            </h2>
            <div className="space-y-2">
              {(topComments as TopComment[]).map((c) => (
                <div key={c.id} className="flex items-start gap-3 py-2 border-b border-white/5 last:border-0">
                  <div className="flex items-center gap-1 text-rose-400 text-xs shrink-0 w-12 justify-end">
                    <Heart size={10} fill="currentColor" /> {c.likes}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-medium text-gray-400">@{c.author}</span>
                      {c.sentiment && (
                        <span className={clsx("text-xs px-1.5 py-0.5 rounded-full", {
                          "badge-positive": c.sentiment === "positive",
                          "badge-negative": c.sentiment === "negative",
                          "badge-neutral":  c.sentiment === "neutral",
                        })}>{c.sentiment}</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-200 truncate">{c.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        </>
      )}

      {/* Posts tab */}
      {activeTab === "posts" && (
        <div className="space-y-2">
          {posts.length === 0 ? (
            <div className="card text-gray-400 text-sm">No posts scraped yet.</div>
          ) : posts.map((p: Post) => (
            <div key={p.id} className="card flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <a href={p.url} target="_blank" rel="noopener noreferrer"
                  className="text-sm text-brand-400 hover:underline truncate block">{p.url}</a>
                <div className="flex gap-4 mt-1 text-xs text-gray-500">
                  <span>{p.likes.toLocaleString()} likes</span>
                  <span>{p.views.toLocaleString()} views</span>
                  <span>{p.comment_count} comments</span>
                </div>
              </div>
              <span className={clsx("text-xs font-medium shrink-0", statusColor(p.etl_status))}>{p.etl_status}</span>
            </div>
          ))}
        </div>
      )}

      {/* Comments tab */}
      {activeTab === "comments" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex gap-1">
              {["all", "positive", "negative", "neutral"].map((f) => (
                <button key={f} onClick={() => setSentFilter(f)}
                  className={clsx("px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors", {
                    "bg-brand-600 text-white": sentFilter === f,
                    "bg-dark-700 text-gray-400 hover:text-white": sentFilter !== f,
                  })}>{f}</button>
              ))}
            </div>
            <div className="flex gap-1 ml-auto">
              {(["date", "likes"] as const).map((s) => (
                <button key={s} onClick={() => setCommentSort(s)}
                  className={clsx("px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors flex items-center gap-1", {
                    "bg-dark-600 text-white": commentSort === s,
                    "bg-dark-700 text-gray-400 hover:text-white": commentSort !== s,
                  })}>
                  {s === "likes" ? <><Heart size={9} /> Most Liked</> : "Latest"}
                </button>
              ))}
            </div>
          </div>

          {comments.length === 0 ? (
            <div className="card text-gray-400 text-sm">No comments found.</div>
          ) : (
            <div className="space-y-2">
              {comments.map((c: Comment) => (
                <div key={c.id} className="card">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium text-gray-300">@{c.author || "anonymous"}</span>
                        {c.sentiment && (
                          <span className={clsx("text-xs px-2 py-0.5 rounded-full", {
                            "badge-positive": c.sentiment === "positive",
                            "badge-negative": c.sentiment === "negative",
                            "badge-neutral": c.sentiment === "neutral",
                          })}>{c.sentiment}</span>
                        )}
                        {c.language && <span className="text-xs bg-dark-700 text-gray-500 px-2 py-0.5 rounded-full">{c.language}</span>}
                        {c.posted_at && (
                          <span className="text-xs text-gray-600">{new Date(c.posted_at).toLocaleDateString()}</span>
                        )}
                      </div>
                      <p className="text-sm text-gray-200">{c.raw_text}</p>
                    </div>
                    <div className="text-right shrink-0 space-y-1">
                      {c.sentiment_score !== undefined && (
                        <p className={clsx("text-sm font-bold", {
                          "text-green-400": (c.sentiment_score ?? 0) > 0,
                          "text-red-400": (c.sentiment_score ?? 0) < 0,
                          "text-gray-400": (c.sentiment_score ?? 0) === 0,
                        })}>
                          {(c.sentiment_score ?? 0) > 0 ? "+" : ""}{c.sentiment_score?.toFixed(2)}
                        </p>
                      )}
                      {c.likes > 0 && (
                        <p className="text-xs text-rose-400 flex items-center gap-1 justify-end">
                          <Heart size={9} fill="currentColor" /> {c.likes}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
