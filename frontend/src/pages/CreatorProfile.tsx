import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCreator, getCreatorPosts, getCreatorComments, getTopComments, refreshCreator, stopCreator, finalizeCreator, recomputeTopics, summarizePost, getPostTopics, getPostComments, rescrapePost } from "../services/api";
import {
  RefreshCw, ArrowLeft, MessageSquare, Loader, Heart,
  CheckCircle, AlertCircle, ExternalLink, Square, CheckSquare, Users, Star, Eye, ThumbsUp, Repeat2,
  Sparkles, Film, Image, LayoutGrid, UserPlus, EyeOff
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer
} from "recharts";
import { clsx } from "clsx";
import { useChartTheme } from "../contexts/ThemeContext";

const SENTIMENT_COLORS = { positive: "#22c55e", negative: "#ef4444", neutral: "#6b7280" };

type Post = {
  id: number; url: string; external_id: string;
  likes: number; views: number; comment_count: number;
  etl_status: string; scraped_at: string; posted_at?: string;
  caption?: string; media_type?: number;
  is_collab?: boolean; counts_disabled?: boolean;
  tags?: string[]; thumbnail_url?: string;
};
type Comment = { id: number; author: string; raw_text: string; sentiment?: string; sentiment_score?: number; language?: string; likes: number; posted_at?: string };
type TopComment = { id: number; author: string; text: string; likes: number; sentiment?: string; sentiment_score?: number; posted_at?: string };
type CreatorData = { avg_views?: number; avg_likes?: number; [key: string]: any };

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
  const chart = useChartTheme();
  const [sentFilter, setSentFilter] = useState("all");
  const [commentSort, setCommentSort] = useState<"date" | "likes">("date");
  const [activeTab, setActiveTab] = useState<"overview" | "posts" | "comments">("overview");
  const [avatarBroken, setAvatarBroken] = useState(false);

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

  const finalize = useMutation({
    mutationFn: () => finalizeCreator(creatorId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["creator", creatorId] }),
  });

  const redoTopics = useMutation({
    mutationFn: () => recomputeTopics(creatorId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["creator", creatorId] });
      const n = data?.topics?.length ?? 0;
      alert(n > 0 ? `Topics updated: ${n} themes extracted.` : "No topics found — not enough comment data yet.");
    },
    onError: (err: any) => alert(`Topic extraction failed: ${err?.response?.data?.detail ?? err.message}`),
  });

  if (isLoading) return <div className="text-gray-400 text-sm">Loading...</div>;
  if (!creator) return <div className="text-red-400 text-sm">Creator not found.</div>;

  const mediaLabel = (t?: number) =>
    t === 2 ? "Reel" : t === 8 ? "Carousel" : "Photo";
  const MediaIcon = (t?: number) =>
    t === 2 ? <Film size={11} /> : t === 8 ? <LayoutGrid size={11} /> : <Image size={11} />;
  const mediaColor = (t?: number) =>
    t === 2 ? "text-purple-400 bg-purple-500/10" : t === 8 ? "text-blue-400 bg-blue-500/10" : "text-gray-400 bg-gray-500/10";

  const isRunning = ["discovering","scraping","processing"].includes(creator.status);

  const pieData = [
    { name: "Positive", value: creator.positive_pct },
    { name: "Negative", value: creator.negative_pct },
    { name: "Neutral",  value: creator.neutral_pct },
  ];

  const topTopics = (creator.top_topics ?? []).slice(0, 10) as { topic: string; count: number }[];
  const maxTopicCount = topTopics.reduce((m, t) => Math.max(m, t.count), 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button onClick={() => navigate("/creators")} className="mt-1 text-gray-500 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            {creator.avatar_url && !avatarBroken ? (
              <img
                src={creator.avatar_url.startsWith("/")
                  ? creator.avatar_url
                  : `/api/proxy/image?url=${encodeURIComponent(creator.avatar_url)}`}
                alt={creator.username}
                className="w-14 h-14 rounded-full object-cover border border-white/10 shrink-0"
                onError={() => setAvatarBroken(true)} />
            ) : (
              <div className="w-14 h-14 rounded-full bg-brand-600/20 flex items-center justify-center text-brand-400 font-bold text-2xl shrink-0">
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
          <div className="flex gap-2">
            <button onClick={() => finalize.mutate()} disabled={finalize.isPending}
              className="flex items-center gap-2 bg-green-500/10 hover:bg-green-500/20 disabled:opacity-50 border border-green-500/30 text-green-400 px-4 py-2 rounded-lg text-sm transition-colors"
              title="Stop scraping and save all collected data">
              <CheckSquare size={14} />
              End & Save
            </button>
            <button onClick={() => stop.mutate()} disabled={stop.isPending}
              className="flex items-center gap-2 bg-yellow-500/10 hover:bg-yellow-500/20 disabled:opacity-50 border border-yellow-500/30 text-yellow-400 px-4 py-2 rounded-lg text-sm transition-colors"
              title="Stop pipeline immediately">
              <Square size={14} />
              Stop
            </button>
          </div>
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
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
        <div className="card"><p className="text-xs text-gray-400">Followers</p><p className="text-2xl font-bold mt-1">{fmtFollowers(creator.follower_count) ?? `${creator.total_posts_scraped} posts`}</p></div>
        <div className="card"><p className="text-xs text-gray-400">Comments</p><p className="text-2xl font-bold mt-1">{creator.total_comments.toLocaleString()}</p></div>
        <div className="card"><p className="text-xs text-gray-400 flex items-center gap-1"><Eye size={10} />Avg views</p><p className="text-2xl font-bold mt-1">{creator.avg_views > 0 ? fmtFollowers(creator.avg_views) : "—"}</p></div>
        <div className="card"><p className="text-xs text-gray-400 flex items-center gap-1"><ThumbsUp size={10} />Avg likes</p><p className="text-2xl font-bold mt-1">{creator.avg_likes > 0 ? fmtFollowers(creator.avg_likes) : "—"}</p></div>
        {creator.platform !== "youtube" && (
          <div className="card"><p className="text-xs text-gray-400 flex items-center gap-1"><Repeat2 size={10} />Avg reposts</p><p className="text-2xl font-bold mt-1">{creator.avg_shares > 0 ? fmtFollowers(creator.avg_shares) : "—"}</p></div>
        )}
        <div className="card"><p className="text-xs text-gray-400">Positive</p><p className="text-2xl font-bold mt-1 text-green-400">{creator.positive_pct}%</p></div>
        <div className="card"><p className="text-xs text-gray-400">Negative</p><p className="text-2xl font-bold mt-1 text-red-400">{creator.negative_pct}%</p></div>
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
                  <Tooltip formatter={(v: number) => `${v}%`} contentStyle={chart.tooltip} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm">No data yet.</p>
            )}
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">Trending Topics</h2>
              <button
                onClick={() => redoTopics.mutate()}
                disabled={redoTopics.isPending || isRunning}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand-600/15 hover:bg-brand-600/30 text-brand-400 border border-brand-500/20 disabled:opacity-40 transition-colors"
                title="Re-run AI topic extraction on existing comments"
              >
                <RefreshCw size={12} className={redoTopics.isPending ? "animate-spin" : ""} />
                {redoTopics.isPending ? "Analyzing…" : "Redo"}
              </button>
            </div>
            {topTopics.length > 0 ? (
              <div className="space-y-2.5">
                {topTopics.map((t) => (
                  <div key={t.topic} className="flex items-center gap-3">
                    <span className="text-sm text-gray-300 w-44 shrink-0" title={t.topic}>
                      {t.topic}
                    </span>
                    <div className="flex-1 bg-dark-700 rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-brand-500 h-2 rounded-full transition-all"
                        style={{ width: `${Math.round((t.count / maxTopicCount) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 w-10 text-right shrink-0">{t.count}</span>
                  </div>
                ))}
              </div>
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
        <div className="space-y-3">
          {posts.length === 0 ? (
            <div className="card text-gray-400 text-sm">No posts scraped yet.</div>
          ) : posts.map((p: Post, idx: number) => (
            <PostCard
              key={p.id}
              post={p}
              index={idx + 1}
              creatorId={creatorId}
              mediaLabel={mediaLabel}
              MediaIcon={MediaIcon}
              mediaColor={mediaColor}
              statusColor={statusColor}
            />
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

// ── PostCard ──────────────────────────────────────────────────────────────────

function PostCard({
  post, index, creatorId, mediaLabel, MediaIcon, mediaColor, statusColor
}: {
  post: Post;
  index: number;
  creatorId: number;
  mediaLabel: (t?: number) => string;
  MediaIcon: (t?: number) => React.ReactElement;
  mediaColor: (t?: number) => string;
  statusColor: (s: string) => string;
}) {
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  type Topic = { topic: string; count: number };
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [loadingTopics, setLoadingTopics] = useState(false);
  const [topicsOpen, setTopicsOpen] = useState(false);

  const [topicsError, setTopicsError] = useState<string | null>(null);
  const [rescraping, setRescraping] = useState(false);
  const [rescrapeMsg, setRescrapeMsg] = useState<string | null>(null);

  const handleRescrape = async () => {
    setRescraping(true);
    setRescrapeMsg(null);
    try {
      await rescrapePost(creatorId, post.id);
      setRescrapeMsg("Rescrape queued — refresh the post list in a minute.");
    } catch (e: any) {
      setRescrapeMsg(e?.response?.data?.detail ?? "Rescrape failed");
    } finally {
      setRescraping(false);
    }
  };

  type PostComment = { id: number; author: string; raw_text: string; likes: number; sentiment?: string; sentiment_score?: number; posted_at?: string };
  const [commentsData, setCommentsData] = useState<{ total: number; comments: PostComment[] } | null>(null);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [loadingComments, setLoadingComments] = useState(false);
  const [commentSentFilter, setCommentSentFilter] = useState<string>("all");
  const [commentPage, setCommentPage] = useState(0);
  const COMMENTS_PER_PAGE = 20;

  const fetchComments = async (sentiment: string, page: number) => {
    setLoadingComments(true);
    try {
      const data = await getPostComments(creatorId, post.id, {
        sentiment: sentiment === "all" ? undefined : sentiment,
        sort: "likes",
        limit: COMMENTS_PER_PAGE,
        offset: page * COMMENTS_PER_PAGE,
      });
      setCommentsData(data);
    } finally {
      setLoadingComments(false);
    }
  };

  const handleComments = async () => {
    if (commentsData && commentsOpen) { setCommentsOpen(false); return; }
    if (!commentsOpen) {
      setCommentsOpen(true);
      if (!commentsData) await fetchComments(commentSentFilter, 0);
    }
  };

  const handleSentimentChange = async (s: string) => {
    setCommentSentFilter(s);
    setCommentPage(0);
    await fetchComments(s, 0);
  };

  const handleTopics = async () => {
    if (topics) { setTopicsOpen((o) => !o); return; }
    setLoadingTopics(true);
    setTopicsError(null);
    try {
      const data = await getPostTopics(creatorId, post.id);
      setTopics(data.topics ?? []);
      setTopicsOpen(true);
    } catch (e: any) {
      setTopicsError(e?.response?.data?.detail ?? "AI topic engine unavailable");
    } finally {
      setLoadingTopics(false);
    }
  };

  const handleSummarize = async () => {
    if (summary) { setExpanded((e) => !e); return; }
    setSummarizing(true);
    setSummaryError(null);
    try {
      const data = await summarizePost(creatorId, post.id);
      setSummary(data.summary);
      setExpanded(true);
    } catch (e: any) {
      setSummaryError(e?.response?.data?.detail ?? "Summary failed");
    } finally {
      setSummarizing(false);
    }
  };

  const [thumbBroken, setThumbBroken] = useState(false);

  // Extract shortcode from URL for a readable post ID
  const shortcode = post.url?.match(/\/(p|reel)\/([A-Za-z0-9_-]+)/)?.[2] ?? post.external_id.slice(-8);
  const proxiedThumb = post.thumbnail_url
    ? post.thumbnail_url.startsWith("/api/thumbnails/")
      ? post.thumbnail_url
      : `/api/proxy/image?url=${encodeURIComponent(post.thumbnail_url)}`
    : null;

  return (
    <div className="card flex gap-3">
      {/* Thumbnail */}
      {proxiedThumb && !thumbBroken ? (
        <img
          src={proxiedThumb}
          alt="post thumbnail"
          onError={() => setThumbBroken(true)}
          className="w-20 h-20 rounded-lg object-cover shrink-0 bg-dark-700"
        />
      ) : (
        <div className="w-20 h-20 rounded-lg bg-dark-700 shrink-0 flex items-center justify-center text-gray-700">
          {MediaIcon(post.media_type)}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-2">
      {/* Row 1: index + type badge + shortcode + date + status */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-600 font-mono w-6 shrink-0">#{index}</span>
        <span className={clsx("flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium", mediaColor(post.media_type))}>
          {MediaIcon(post.media_type)} {mediaLabel(post.media_type)}
        </span>
        {post.is_collab && (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full text-orange-400 bg-orange-500/10 font-medium">
            <UserPlus size={10} /> Collab
          </span>
        )}
        {post.counts_disabled && (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full text-gray-500 bg-gray-500/10 font-medium">
            <EyeOff size={10} /> Counts hidden
          </span>
        )}
        <code className="text-xs text-gray-600 font-mono">{shortcode}</code>
        {post.posted_at && (
          <span className="text-xs text-gray-600 ml-auto">
            {new Date(post.posted_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
          </span>
        )}
        <span className={clsx("text-xs font-medium shrink-0", statusColor(post.etl_status))}>{post.etl_status}</span>
      </div>

      {/* Row 2: caption */}
      {post.caption ? (
        <p className="text-sm text-gray-300 line-clamp-2">{post.caption}</p>
      ) : (
        <p className="text-xs text-gray-600 italic">No caption</p>
      )}

      {/* Row 3: tags */}
      {(post.tags ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {(post.tags ?? []).slice(0, 8).map((t) => (
            <span key={t} className="text-xs text-brand-400 bg-brand-500/10 px-1.5 py-0.5 rounded">#{t}</span>
          ))}
        </div>
      )}

      {/* Row 4: metrics + link + summarize button */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1"><ThumbsUp size={10} /> {(post.likes || 0).toLocaleString()}</span>
          {post.media_type === 2 && (
            <span className="flex items-center gap-1"><Eye size={10} /> {(post.views || 0).toLocaleString()}</span>
          )}
          <span className="flex items-center gap-1"><MessageSquare size={10} /> {post.comment_count}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <a href={post.url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-brand-400 hover:underline">
            <ExternalLink size={11} /> Open
          </a>
          <button
            onClick={handleRescrape}
            disabled={rescraping}
            title="Re-scrape all comments for this post"
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-dark-700 hover:bg-dark-600 text-gray-500 border border-white/5 disabled:opacity-50 transition-colors"
          >
            {rescraping ? <Loader size={10} className="animate-spin" /> : <RefreshCw size={10} />}
          </button>
          <button
            onClick={handleComments}
            disabled={loadingComments}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-dark-700 hover:bg-dark-600 text-gray-400 border border-white/10 disabled:opacity-50 transition-colors"
          >
            {loadingComments ? <Loader size={11} className="animate-spin" /> : <MessageSquare size={11} />}
            {commentsOpen ? "Hide comments" : "Comments"}
          </button>
          <button
            onClick={handleTopics}
            disabled={loadingTopics}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-dark-700 hover:bg-dark-600 text-gray-400 border border-white/10 disabled:opacity-50 transition-colors"
          >
            {loadingTopics ? <Loader size={11} className="animate-spin" /> : <MessageSquare size={11} />}
            {topics ? (topicsOpen ? "Hide topics" : "Topics") : loadingTopics ? "Loading…" : "Topics"}
          </button>
          <button
            onClick={handleSummarize}
            disabled={summarizing}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-brand-600/15 hover:bg-brand-600/30 text-brand-400 border border-brand-500/20 disabled:opacity-50 transition-colors"
          >
            {summarizing ? <Loader size={11} className="animate-spin" /> : <Sparkles size={11} />}
            {summary ? (expanded ? "Hide" : "Show summary") : summarizing ? "Summarizing…" : "AI Summary"}
          </button>
        </div>
      </div>

      {/* Comments panel */}
      {commentsOpen && (
        <div className="border border-white/5 rounded-lg overflow-hidden">
          {/* Filter bar */}
          <div className="flex items-center gap-1 px-3 py-2 bg-dark-800/60 border-b border-white/5 flex-wrap">
            <span className="text-xs text-gray-500 mr-1">Sentiment:</span>
            {["all", "positive", "negative", "neutral"].map((s) => (
              <button key={s} onClick={() => handleSentimentChange(s)}
                className={clsx("px-2 py-0.5 rounded text-xs capitalize transition-colors", {
                  "bg-brand-600 text-white": commentSentFilter === s,
                  "text-gray-400 hover:text-white": commentSentFilter !== s,
                })}>{s}</button>
            ))}
            {commentsData && (
              <span className="ml-auto text-xs text-gray-600">{commentsData.total.toLocaleString()} comments</span>
            )}
          </div>

          {/* Comment list */}
          {loadingComments ? (
            <div className="flex items-center justify-center py-6 text-gray-600">
              <Loader size={14} className="animate-spin mr-2" /> Loading…
            </div>
          ) : commentsData && commentsData.comments.length === 0 ? (
            <p className="text-xs text-gray-600 italic px-3 py-4">No comments match this filter.</p>
          ) : (
            <div className="divide-y divide-white/5 max-h-80 overflow-y-auto">
              {(commentsData?.comments ?? []).map((c) => (
                <div key={c.id} className="px-3 py-2 flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="text-xs font-medium text-gray-400">@{c.author}</span>
                      {c.sentiment && (
                        <span className={clsx("text-xs px-1.5 py-0.5 rounded-full", {
                          "badge-positive": c.sentiment === "positive",
                          "badge-negative": c.sentiment === "negative",
                          "badge-neutral":  c.sentiment === "neutral",
                        })}>{c.sentiment}</span>
                      )}
                      {c.posted_at && (
                        <span className="text-xs text-gray-600">{new Date(c.posted_at).toLocaleDateString()}</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-200">{c.raw_text}</p>
                  </div>
                  <div className="shrink-0 text-right space-y-0.5">
                    {c.likes > 0 && (
                      <p className="text-xs text-rose-400 flex items-center gap-1 justify-end">
                        <Heart size={9} fill="currentColor" /> {c.likes}
                      </p>
                    )}
                    {c.sentiment_score !== undefined && c.sentiment_score !== null && (
                      <p className={clsx("text-xs font-mono", {
                        "text-green-400": (c.sentiment_score ?? 0) > 0,
                        "text-red-400": (c.sentiment_score ?? 0) < 0,
                        "text-gray-500": (c.sentiment_score ?? 0) === 0,
                      })}>{(c.sentiment_score ?? 0) > 0 ? "+" : ""}{c.sentiment_score?.toFixed(2)}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {commentsData && commentsData.total > COMMENTS_PER_PAGE && (
            <div className="flex items-center justify-between px-3 py-2 border-t border-white/5 bg-dark-800/60">
              <button
                onClick={async () => { const p = commentPage - 1; setCommentPage(p); await fetchComments(commentSentFilter, p); }}
                disabled={commentPage === 0 || loadingComments}
                className="text-xs text-gray-400 hover:text-white disabled:opacity-30 px-2 py-1 rounded"
              >← Prev</button>
              <span className="text-xs text-gray-600">
                {commentPage * COMMENTS_PER_PAGE + 1}–{Math.min((commentPage + 1) * COMMENTS_PER_PAGE, commentsData.total)} of {commentsData.total.toLocaleString()}
              </span>
              <button
                onClick={async () => { const p = commentPage + 1; setCommentPage(p); await fetchComments(commentSentFilter, p); }}
                disabled={(commentPage + 1) * COMMENTS_PER_PAGE >= commentsData.total || loadingComments}
                className="text-xs text-gray-400 hover:text-white disabled:opacity-30 px-2 py-1 rounded"
              >Next →</button>
            </div>
          )}
        </div>
      )}

      {rescrapeMsg && (
        <p className={`text-xs ${rescrapeMsg.includes("queued") ? "text-green-400" : "text-red-400"}`}>{rescrapeMsg}</p>
      )}

      {/* Topics error */}
      {topicsError && <p className="text-xs text-red-400">{topicsError}</p>}

      {/* Topics panel */}
      {topicsOpen && topics && (
        <div className="bg-dark-800/60 border border-white/5 rounded-lg px-3 py-2.5 space-y-2">
          {topics.length === 0 ? (
            <p className="text-xs text-gray-600 italic">No topics found — not enough comments analyzed yet.</p>
          ) : (
            <>
              <p className="text-xs text-gray-500 font-medium">Trending in comments</p>
              <div className="space-y-1.5">
                {topics.map((t) => (
                  <div key={t.topic} className="flex items-center gap-2">
                    <span className="text-xs text-gray-300 w-32 shrink-0 truncate">{t.topic}</span>
                    <div className="flex-1 bg-dark-700 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-brand-500/70 h-1.5 rounded-full"
                        style={{ width: `${Math.round((t.count / topics[0].count) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600 w-6 text-right shrink-0">{t.count}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* AI summary box */}
      {expanded && summary && (
        <div className="bg-brand-500/5 border border-brand-500/20 rounded-lg px-3 py-2 text-sm text-gray-200">
          {summary}
        </div>
      )}
      {summaryError && (
        <p className="text-xs text-red-400">{summaryError}</p>
      )}
      </div>{/* end content */}
    </div>
  );
}
