import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getCreators, addCreator, deleteCreator, refreshCreator, resetCreator, stopCreator, restartCreator, finalizeCreator, getCampaigns } from "../services/api";
import { Plus, RefreshCw, Trash2, ChevronRight, Loader, CheckCircle, AlertCircle, Search, Square, RotateCcw, CheckSquare } from "lucide-react";
import { clsx } from "clsx";

const PLATFORMS = ["instagram", "youtube"];

type Creator = {
  id: number; username: string; display_name?: string; platform_id: number;
  status: string; total_posts_scraped: number; total_comments: number;
  positive_pct: number; negative_pct: number; neutral_pct: number;
  audience_mood?: string; last_pipeline_at?: string; error_message?: string;
  campaign_id?: number; follower_count: number; avatar_url?: string; bio?: string;
};

const fmt = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n > 0 ? n.toString() : null;
};

const tier = (n: number) => {
  if (n >= 1_000_000) return { label: "Mega",  cls: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" };
  if (n >= 100_000)   return { label: "Macro", cls: "text-purple-400 bg-purple-500/10 border-purple-500/20" };
  if (n >= 10_000)    return { label: "Micro", cls: "text-blue-400 bg-blue-500/10 border-blue-500/20" };
  if (n > 0)          return { label: "Nano",  cls: "text-green-400 bg-green-500/10 border-green-500/20" };
  return null;
};

function CreatorAvatar({ url, username }: { url?: string; username: string }) {
  const [broken, setBroken] = useState(false);
  const proxied = url
    ? url.startsWith("/")
      ? url
      : `/api/proxy/image?url=${encodeURIComponent(url)}`
    : null;
  if (proxied && !broken) {
    return (
      <img src={proxied} alt={username}
        className="w-11 h-11 rounded-full object-cover shrink-0 border border-white/10"
        onError={() => setBroken(true)} />
    );
  }
  return (
    <div className="w-11 h-11 rounded-full bg-brand-600/20 flex items-center justify-center text-brand-400 font-bold text-lg shrink-0">
      {username[0]?.toUpperCase()}
    </div>
  );
}

const StatusBadge = ({ status }: { status: string }) => {
  const map: Record<string, { color: string; icon: React.ReactNode }> = {
    idle:        { color: "text-gray-400 bg-gray-500/10",  icon: null },
    discovering: { color: "text-blue-400 bg-blue-500/10",  icon: <Loader size={10} className="animate-spin" /> },
    scraping:    { color: "text-yellow-400 bg-yellow-500/10", icon: <Loader size={10} className="animate-spin" /> },
    processing:  { color: "text-purple-400 bg-purple-500/10", icon: <Loader size={10} className="animate-spin" /> },
    done:        { color: "text-green-400 bg-green-500/10",  icon: <CheckCircle size={10} /> },
    error:       { color: "text-red-400 bg-red-500/10",     icon: <AlertCircle size={10} /> },
  };
  const cfg = map[status] ?? map.idle;
  return (
    <span className={clsx("flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium", cfg.color)}>
      {cfg.icon}{status}
    </span>
  );
};

const MoodBar = ({ positive, negative, neutral }: { positive: number; negative: number; neutral: number }) => (
  <div className="flex rounded-full overflow-hidden h-1.5 w-full">
    <div className="bg-green-500" style={{ width: `${positive}%` }} />
    <div className="bg-gray-500"  style={{ width: `${neutral}%` }} />
    <div className="bg-red-500"   style={{ width: `${negative}%` }} />
  </div>
);

export default function Creators() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ username: "", platform: "instagram", campaign_id: "" });

  const { data: creators = [], isLoading } = useQuery({
    queryKey: ["creators"],
    queryFn: getCreators,
    placeholderData: (prev: Creator[] | undefined) => prev,
    refetchInterval: (query) => {
      const data = query.state.data as Creator[] | undefined;
      return (data ?? []).some((c) => ["discovering", "scraping", "processing"].includes(c.status)) ? 4000 : false;
    },
  });

  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const add = useMutation({
    mutationFn: () => addCreator({
      username: form.username,
      platform: form.platform,
      campaign_id: form.campaign_id ? parseInt(form.campaign_id) : undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["creators"] }); setShowForm(false); setForm({ username: "", platform: "instagram", campaign_id: "" }); },
  });

  const patchCreator = (id: number, patch: Partial<Creator>) =>
    qc.setQueryData(["creators"], (old: Creator[] | undefined) =>
      (old ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c))
    );

  const removeCreatorFromCache = (id: number) =>
    qc.setQueryData(["creators"], (old: Creator[] | undefined) =>
      (old ?? []).filter((c) => c.id !== id)
    );

  const remove = useMutation({
    mutationFn: (id: number) => deleteCreator(id),
    onMutate: (id) => removeCreatorFromCache(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  const refresh = useMutation({
    mutationFn: (id: number) => refreshCreator(id),
    onMutate: (id) => patchCreator(id, { status: "discovering", error_message: undefined }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  const reset = useMutation({
    mutationFn: (id: number) => resetCreator(id),
    onMutate: (id) => removeCreatorFromCache(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  const stop = useMutation({
    mutationFn: (id: number) => stopCreator(id),
    onMutate: (id) => patchCreator(id, { status: "idle" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  const finalize = useMutation({
    mutationFn: (id: number) => finalizeCreator(id),
    onMutate: (id) => patchCreator(id, { status: "processing" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  const restart = useMutation({
    mutationFn: (id: number) => restartCreator(id),
    onMutate: (id) =>
      patchCreator(id, {
        status: "discovering",
        error_message: undefined,
        total_comments: 0,
        total_posts_scraped: 0,
        positive_pct: 0,
        negative_pct: 0,
        neutral_pct: 0,
        audience_mood: undefined,
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Creators</h1>
          <p className="text-gray-400 text-sm">Add a creator — automatic full pipeline runs instantly</p>
        </div>
        <button onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          <Plus size={16} /> Track Creator
        </button>
      </div>

      {showForm && (
        <div className="card space-y-4 max-w-lg">
          <h2 className="font-semibold">Track New Creator</h2>
          <p className="text-xs text-gray-400">
            Enter a username or profile URL. Sentinelle will discover all their posts,
            scrape comments, arabize Tunisian Arabizi, run sentiment analysis, and build
            their profile — fully automated.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Username or URL</label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  placeholder="@username or profile URL"
                  className="w-full bg-dark-700 border border-white/10 rounded-lg pl-8 pr-3 py-2 text-sm focus:outline-none focus:border-brand-500"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Platform</label>
              <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}
                className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
                {PLATFORMS.map((p) => <option key={p} value={p} className="capitalize">{p}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Link to Campaign (optional)</label>
            <select value={form.campaign_id} onChange={(e) => setForm({ ...form, campaign_id: e.target.value })}
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="">— none (Global Pool) —</option>
              {campaigns.map((c: { id: number; name: string }) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-3">
            <button onClick={() => add.mutate()} disabled={!form.username || add.isPending}
              className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
              {add.isPending ? <Loader size={14} className="animate-spin" /> : <Plus size={14} />}
              Start Pipeline
            </button>
            <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white text-sm px-4 py-2">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading...</div>
      ) : creators.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400">No creators tracked yet.</p>
          <p className="text-gray-500 text-sm mt-1">Add a creator above to start the automated pipeline.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {creators.map((c: Creator) => (
            <div key={c.id} className="card hover:border-white/10 transition-colors cursor-pointer group"
              onClick={() => navigate(`/creators/${c.id}`)}>
              <div className="flex items-center gap-4">
                <CreatorAvatar url={c.avatar_url} username={c.username} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold">@{c.username}</span>
                    {c.display_name && <span className="text-xs text-gray-500">{c.display_name}</span>}
                    <StatusBadge status={c.status} />
                    {(() => { const t = tier(c.follower_count); return t ? (
                      <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${t.cls}`}>{t.label}</span>
                    ) : null; })()}
                    {fmt(c.follower_count) && (
                      <span className="text-xs text-gray-400">{fmt(c.follower_count)} followers</span>
                    )}
                    {c.audience_mood && (
                      <span className="text-xs text-gray-500 capitalize">{c.audience_mood} mood</span>
                    )}
                    {!c.campaign_id && (
                      <span className="text-xs bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded-full">Global Pool</span>
                    )}
                  </div>

                  {c.status === "error" && c.error_message && (
                    <p className="text-xs text-red-400 mt-1 truncate">{c.error_message}</p>
                  )}

                  {c.total_comments > 0 && (
                    <div className="mt-2 space-y-1">
                      <MoodBar positive={c.positive_pct} negative={c.negative_pct} neutral={c.neutral_pct} />
                      <div className="flex gap-3 text-xs text-gray-500">
                        <span className="text-green-400">{c.positive_pct}% positive</span>
                        <span className="text-gray-400">{c.neutral_pct}% neutral</span>
                        <span className="text-red-400">{c.negative_pct}% negative</span>
                        <span className="ml-auto">{c.total_comments.toLocaleString()} comments · {c.total_posts_scraped} posts</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                  {["discovering", "scraping", "processing"].includes(c.status) ? (
                    <>
                      <button onClick={() => finalize.mutate(c.id)}
                        className="p-2 text-green-500 hover:text-green-300 transition-colors rounded-lg hover:bg-green-500/10"
                        title="End scraping and save collected data">
                        <CheckSquare size={15} />
                      </button>
                      <button onClick={() => stop.mutate(c.id)}
                        className="p-2 text-yellow-500 hover:text-yellow-300 transition-colors rounded-lg hover:bg-yellow-500/10"
                        title="Stop pipeline (discard in-flight)">
                        <Square size={15} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => refresh.mutate(c.id)}
                        className="p-2 text-gray-500 hover:text-brand-400 transition-colors rounded-lg hover:bg-brand-500/10"
                        title="Re-run pipeline (skip already scraped)">
                        <RefreshCw size={15} />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Restart @${c.username} from scratch? This will delete all comments and re-scrape every post.`))
                            restart.mutate(c.id);
                        }}
                        className="p-2 text-gray-500 hover:text-orange-400 transition-colors rounded-lg hover:bg-orange-500/10"
                        title="Restart from scratch (wipe and re-scrape all)">
                        <RotateCcw size={15} />
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => {
                      if (confirm(`Delete @${c.username}? This will stop the pipeline and permanently delete all posts, comments, and raw files.`))
                        reset.mutate(c.id);
                    }}
                    className="p-2 text-gray-500 hover:text-red-400 transition-colors rounded-lg hover:bg-red-500/10"
                    title="Delete creator and all data">
                    <Trash2 size={15} />
                  </button>
                  <ChevronRight size={16} className="text-gray-600 group-hover:text-gray-400 transition-colors ml-1" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
