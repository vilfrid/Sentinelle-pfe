import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getReports, generateReport, getCampaigns } from "../services/api";
import { FileText, CheckCircle, TrendingUp, AlertTriangle, Lightbulb } from "lucide-react";
import { format } from "date-fns";

type Report = {
  id: number; campaign_id: number; title: string; summary?: string;
  what_worked: string[]; what_to_improve: string[]; recommendations: string[];
  metrics_snapshot: Record<string, unknown>; status: string; created_at: string;
};

export default function Reports() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ campaign_id: "", title: "" });
  const { data: reports = [], isLoading } = useQuery({ queryKey: ["reports"], queryFn: getReports });
  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });
  const [selected, setSelected] = useState<Report | null>(null);

  const generate = useMutation({
    mutationFn: () => generateReport({ campaign_id: parseInt(form.campaign_id), title: form.title }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["reports"] }); setSelected(r); },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Reports</h1>
        <p className="text-gray-400 text-sm">Generate and view campaign performance reports</p>
      </div>

      <div className="card space-y-4 max-w-lg">
        <h2 className="font-semibold">Generate Report</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Campaign</label>
            <select value={form.campaign_id} onChange={(e) => setForm({ ...form, campaign_id: e.target.value })}
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="">Select campaign</option>
              {campaigns.map((c: { id: number; name: string }) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Report Title</label>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Weekly Summary"
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500" />
          </div>
        </div>
        <button onClick={() => generate.mutate()} disabled={!form.campaign_id || !form.title}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
          <FileText size={14} /> Generate
        </button>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Report list */}
        <div className="space-y-3">
          {isLoading ? <p className="text-gray-400 text-sm">Loading...</p> : reports.map((r: Report) => (
            <button key={r.id} onClick={() => setSelected(r)}
              className={`w-full text-left card hover:border-brand-500/30 transition-colors ${selected?.id === r.id ? "border-brand-500/50" : ""}`}>
              <p className="font-medium text-sm">{r.title}</p>
              <p className="text-xs text-gray-400 mt-1">Campaign #{r.campaign_id} · {format(new Date(r.created_at), "MMM d, yyyy")}</p>
              {r.summary && <p className="text-xs text-gray-500 mt-2 line-clamp-2">{r.summary}</p>}
            </button>
          ))}
        </div>

        {/* Report detail */}
        {selected && (
          <div className="card space-y-5">
            <h2 className="font-bold text-lg">{selected.title}</h2>
            {selected.summary && <p className="text-sm text-gray-300">{selected.summary}</p>}

            {Object.keys(selected.metrics_snapshot).length > 0 && (
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(selected.metrics_snapshot).map(([k, v]) => (
                  <div key={k} className="bg-dark-700 rounded-lg px-3 py-2">
                    <p className="text-xs text-gray-400 capitalize">{k.replace(/_/g, " ")}</p>
                    <p className="text-sm font-semibold mt-0.5">{String(v)}</p>
                  </div>
                ))}
              </div>
            )}

            {selected.what_worked.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-green-400 mb-2"><CheckCircle size={14} /><span className="text-sm font-medium">What Worked</span></div>
                <ul className="space-y-1">{selected.what_worked.map((w, i) => <li key={i} className="text-sm text-gray-300 flex gap-2"><span className="text-green-400">•</span>{w}</li>)}</ul>
              </div>
            )}
            {selected.what_to_improve.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-orange-400 mb-2"><AlertTriangle size={14} /><span className="text-sm font-medium">To Improve</span></div>
                <ul className="space-y-1">{selected.what_to_improve.map((w, i) => <li key={i} className="text-sm text-gray-300 flex gap-2"><span className="text-orange-400">•</span>{w}</li>)}</ul>
              </div>
            )}
            {selected.recommendations.length > 0 && (
              <div>
                <div className="flex items-center gap-2 text-brand-400 mb-2"><Lightbulb size={14} /><span className="text-sm font-medium">Recommendations</span></div>
                <ul className="space-y-1">{selected.recommendations.map((r, i) => <li key={i} className="text-sm text-gray-300 flex gap-2"><span className="text-brand-400">•</span>{r}</li>)}</ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
