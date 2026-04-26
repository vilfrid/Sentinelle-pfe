import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getCampaigns, createCampaign, deleteCampaign } from "../services/api";
import { Plus, Trash2, Tag } from "lucide-react";

type Campaign = {
  id: number; name: string; brand: string; status: string;
  keywords: string[]; target_platforms: string[]; created_at: string;
};

const PLATFORMS = ["instagram", "tiktok", "youtube", "facebook"];

export default function Campaigns() {
  const qc = useQueryClient();
  const { data: campaigns = [], isLoading } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });

  const [form, setForm] = useState({ name: "", brand: "", description: "", keywords: "", target_platforms: [] as string[] });
  const [showForm, setShowForm] = useState(false);

  const create = useMutation({
    mutationFn: () => createCampaign({
      ...form,
      keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["campaigns"] }); setShowForm(false); },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteCampaign(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });

  const togglePlatform = (p: string) => {
    setForm((prev) => ({
      ...prev,
      target_platforms: prev.target_platforms.includes(p)
        ? prev.target_platforms.filter((x) => x !== p)
        : [...prev.target_platforms, p],
    }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Campaigns</h1>
          <p className="text-gray-400 text-sm">Manage your brand monitoring campaigns</p>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          <Plus size={16} /> New Campaign
        </button>
      </div>

      {showForm && (
        <div className="card space-y-4">
          <h2 className="font-semibold">Create Campaign</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Campaign Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500" />
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Brand</label>
              <input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })}
                className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500" />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Keywords (comma-separated)</label>
            <input value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })}
              placeholder="e.g. منتج, تونس, جديد"
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500" />
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-2 block">Target Platforms</label>
            <div className="flex gap-2">
              {PLATFORMS.map((p) => (
                <button key={p} onClick={() => togglePlatform(p)}
                  className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-colors ${
                    form.target_platforms.includes(p) ? "bg-brand-600 text-white" : "bg-dark-700 text-gray-400 hover:text-white"
                  }`}>{p}</button>
              ))}
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={() => create.mutate()} disabled={!form.name || !form.brand}
              className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
              Create
            </button>
            <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white text-sm px-4 py-2">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading...</div>
      ) : (
        <div className="grid gap-4">
          {campaigns.map((c: Campaign) => (
            <div key={c.id} className="card flex items-start justify-between">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <h3 className="font-semibold">{c.name}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${c.status === "active" ? "bg-green-500/20 text-green-400" : "bg-gray-500/20 text-gray-400"}`}>
                    {c.status}
                  </span>
                </div>
                <p className="text-sm text-gray-400">{c.brand}</p>
                {c.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {c.keywords.map((k) => (
                      <span key={k} className="flex items-center gap-1 bg-dark-700 text-xs px-2 py-0.5 rounded-full text-gray-300">
                        <Tag size={10} /> {k}
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex gap-1">
                  {c.target_platforms.map((p) => (
                    <span key={p} className="text-xs bg-brand-600/20 text-brand-400 px-2 py-0.5 rounded-full capitalize">{p}</span>
                  ))}
                </div>
              </div>
              <button onClick={() => remove.mutate(c.id)} className="text-gray-600 hover:text-red-400 transition-colors p-1">
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
