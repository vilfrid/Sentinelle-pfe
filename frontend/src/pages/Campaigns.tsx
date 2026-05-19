import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getCampaigns, createCampaign, deleteCampaign, addCreator, getCreators,
  updateCreator, updateCampaign, suggestKeywords, suggestNewKeywords,
} from "../services/api";
import { Plus, Trash2, Tag, Sparkles, Loader } from "lucide-react";

type Campaign = {
  id: number; name: string; brand: string; status: string;
  keywords: string[]; target_platforms: string[]; created_at: string;
};

const PLATFORMS = ["instagram", "tiktok", "youtube", "facebook"];

export default function Campaigns() {
  const qc = useQueryClient();
  const { data: campaigns = [], isLoading } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });
  const { data: creators = [] } = useQuery({ queryKey: ["creators"], queryFn: getCreators });

  const [form, setForm] = useState({ name: "", brand: "", description: "", keywords: "", target_platforms: [] as string[] });
  const [showForm, setShowForm] = useState(false);
  const [formSuggestions, setFormSuggestions] = useState<string[]>([]);
  const [formSuggesting, setFormSuggesting] = useState(false);

  // Per-campaign keyword refresh state
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [refreshResult, setRefreshResult] = useState<{ id: number; keywords: string[] } | null>(null);

  const create = useMutation({
    mutationFn: () => createCampaign({
      ...form,
      keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setShowForm(false);
      setForm({ name: "", brand: "", description: "", keywords: "", target_platforms: [] });
      setFormSuggestions([]);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteCampaign(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });

  const quickAdd = useMutation({
    mutationFn: (data: { username: string; platform: string; campaign_id: number }) => addCreator(data),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ["creators"] });
      alert(`@${variables.username} added to campaign and is now being scraped!`);
    },
  });

  const linkExisting = useMutation({
    mutationFn: ({ creatorId, campaignId }: { creatorId: number; campaignId: number }) =>
      updateCreator(creatorId, { campaign_id: campaignId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["creators"] });
      alert("Existing creator added to campaign successfully!");
    },
  });

  const applyKeywords = useMutation({
    mutationFn: ({ id, keywords }: { id: number; keywords: string[] }) =>
      updateCampaign(id, { keywords }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setRefreshResult(null);
    },
  });

  const togglePlatform = (p: string) =>
    setForm((prev) => ({
      ...prev,
      target_platforms: prev.target_platforms.includes(p)
        ? prev.target_platforms.filter((x) => x !== p)
        : [...prev.target_platforms, p],
    }));

  // Toggle a suggestion chip into/out of the keywords text field
  const toggleFormChip = (kw: string) => {
    const current = form.keywords.split(",").map((k) => k.trim()).filter(Boolean);
    const next = current.includes(kw) ? current.filter((k) => k !== kw) : [...current, kw];
    setForm({ ...form, keywords: next.join(", ") });
  };

  const activeFormKws = new Set(form.keywords.split(",").map((k) => k.trim()).filter(Boolean));

  const handleSuggestForForm = async () => {
    if (!form.brand) return;
    setFormSuggesting(true);
    setFormSuggestions([]);
    try {
      const data = await suggestNewKeywords({
        name: form.name,
        brand: form.brand,
        description: form.description,
        target_platforms: form.target_platforms,
      });
      const kws = data.keywords || [];
      if (!kws.length) {
        alert("AI returned no keywords. Check that GOOGLE_API_KEY is set and Gemini is reachable.");
      }
      setFormSuggestions(kws);
    } catch {
      alert("Keyword suggestion failed. Check backend logs.");
    } finally {
      setFormSuggesting(false);
    }
  };

  const handleRefreshExisting = async (campaignId: number) => {
    setRefreshingId(campaignId);
    setRefreshResult(null);
    try {
      const data = await suggestKeywords(campaignId);
      const kws = data.keywords || [];
      if (!kws.length) {
        alert("AI returned no keywords. Check that GOOGLE_API_KEY is set and Gemini is reachable.");
      } else {
        setRefreshResult({ id: campaignId, keywords: kws });
      }
    } catch {
      alert("Keyword refresh failed. Check backend logs.");
    } finally {
      setRefreshingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Campaigns</h1>
          <p className="text-gray-400 text-sm">Manage your brand monitoring campaigns</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} /> New Campaign
        </button>
      </div>

      {showForm && (
        <div className="card space-y-4">
          <h2 className="font-semibold">Create Campaign</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Campaign Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Brand</label>
              <input
                value={form.brand}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
                className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Description (optional — helps AI generate better keywords)</label>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="e.g. Summer streetwear collection targeting Tunisian youth"
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-gray-400">Keywords (comma-separated)</label>
              <button
                onClick={handleSuggestForForm}
                disabled={!form.brand || formSuggesting}
                className="flex items-center gap-1.5 text-xs text-purple-400 hover:text-purple-300 disabled:opacity-40 transition-colors"
              >
                {formSuggesting
                  ? <><Loader size={11} className="animate-spin" /> Suggesting…</>
                  : <><Sparkles size={11} /> Suggest with AI</>
                }
              </button>
            </div>
            <input
              value={form.keywords}
              onChange={(e) => setForm({ ...form, keywords: e.target.value })}
              placeholder="e.g. منتج, تونس, جديد"
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
            />
            {formSuggestions.length > 0 && (
              <div className="mt-2 space-y-1">
                <p className="text-xs text-gray-500">Click to add / remove:</p>
                <div className="flex flex-wrap gap-1.5">
                  {formSuggestions.map((kw) => (
                    <button
                      key={kw}
                      onClick={() => toggleFormChip(kw)}
                      className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        activeFormKws.has(kw)
                          ? "bg-purple-600/30 border-purple-500/60 text-purple-300"
                          : "bg-dark-700 border-white/10 text-gray-400 hover:border-purple-500/40 hover:text-purple-300"
                      }`}
                    >
                      <Sparkles size={9} /> {kw}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-2 block">Target Platforms</label>
            <div className="flex gap-2">
              {PLATFORMS.map((p) => (
                <button
                  key={p}
                  onClick={() => togglePlatform(p)}
                  className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-colors ${
                    form.target_platforms.includes(p)
                      ? "bg-brand-600 text-white"
                      : "bg-dark-700 text-gray-400 hover:text-white"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => create.mutate()}
              disabled={!form.name || !form.brand}
              className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              Create
            </button>
            <button
              onClick={() => { setShowForm(false); setFormSuggestions([]); }}
              className="text-gray-400 hover:text-white text-sm px-4 py-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading...</div>
      ) : (
        <div className="grid gap-4">
          <datalist id="global-creators-list">
            {creators.map((cr: any) => (
              <option key={cr.id} value={`@${cr.username}`} />
            ))}
          </datalist>

          {campaigns.map((c: Campaign) => (
            <div key={c.id} className="card space-y-3">
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold">{c.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${c.status === "active" ? "bg-green-500/20 text-green-400" : "bg-gray-500/20 text-gray-400"}`}>
                      {c.status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400">{c.brand}</p>
                </div>
                <button onClick={() => remove.mutate(c.id)} className="text-gray-600 hover:text-red-400 transition-colors p-1">
                  <Trash2 size={16} />
                </button>
              </div>

              {/* Keywords row */}
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-xs text-gray-500">Keywords</span>
                  <button
                    onClick={() => handleRefreshExisting(c.id)}
                    disabled={refreshingId === c.id}
                    title="Regenerate keywords with AI"
                    className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 disabled:opacity-40 transition-colors"
                  >
                    {refreshingId === c.id
                      ? <><Loader size={10} className="animate-spin" /> Thinking…</>
                      : <><Sparkles size={10} /> Refresh with AI</>
                    }
                  </button>
                </div>

                {c.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {c.keywords.map((k) => (
                      <span key={k} className="flex items-center gap-1 bg-dark-700 text-xs px-2 py-0.5 rounded-full text-gray-300">
                        <Tag size={10} /> {k}
                      </span>
                    ))}
                  </div>
                )}

                {/* AI refresh suggestions for this campaign */}
                {refreshResult?.id === c.id && (
                  <div className="mt-2 p-3 bg-purple-500/5 border border-purple-500/20 rounded-lg space-y-2">
                    <p className="text-xs text-purple-300 font-medium">AI-suggested keywords — click Apply to save:</p>
                    <div className="flex flex-wrap gap-1.5">
                      {refreshResult.keywords.map((kw) => (
                        <span key={kw} className="flex items-center gap-1 bg-purple-600/20 text-purple-300 text-xs px-2.5 py-0.5 rounded-full">
                          <Sparkles size={9} /> {kw}
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => applyKeywords.mutate({ id: c.id, keywords: refreshResult.keywords })}
                        disabled={applyKeywords.isPending}
                        className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white px-3 py-1 rounded-lg text-xs font-medium"
                      >
                        Apply
                      </button>
                      <button
                        onClick={() => setRefreshResult(null)}
                        className="text-gray-400 hover:text-white text-xs px-3 py-1"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Platforms */}
              {c.target_platforms.length > 0 && (
                <div className="flex gap-1">
                  {c.target_platforms.map((p) => (
                    <span key={p} className="text-xs bg-brand-600/20 text-brand-400 px-2 py-0.5 rounded-full capitalize">{p}</span>
                  ))}
                </div>
              )}

              {/* Quick-add creator */}
              <div className="pt-1">
                <form
                  className="flex items-center gap-2 bg-dark-700/50 p-1.5 rounded-lg border border-white/5"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const formEl = e.target as HTMLFormElement;
                    let username = (formEl.elements.namedItem("username") as HTMLInputElement).value.trim();
                    const platform = (formEl.elements.namedItem("platform") as HTMLSelectElement).value;
                    if (!username) return;
                    username = username.replace(/^@/, "");
                    const existing = creators.find((cr: any) => cr.username.toLowerCase() === username.toLowerCase());
                    if (existing) {
                      linkExisting.mutate({ creatorId: existing.id, campaignId: c.id });
                    } else {
                      quickAdd.mutate({ username, platform, campaign_id: c.id });
                    }
                    formEl.reset();
                  }}
                >
                  <input
                    name="username"
                    list="global-creators-list"
                    placeholder="@username or search..."
                    className="w-40 bg-transparent border-none text-xs focus:outline-none px-2"
                  />
                  <select name="platform" className="bg-dark-700 text-xs border border-white/10 rounded px-1 py-1 focus:outline-none">
                    {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <button type="submit" className="bg-brand-600 hover:bg-brand-700 text-white p-1 rounded transition-colors" title="Quick Add Creator">
                    <Plus size={14} />
                  </button>
                </form>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
