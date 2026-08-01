import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getReports, generateReport, getCampaigns } from "../services/api";
import {
  FileText, CheckCircle, AlertTriangle, Lightbulb,
  AlertOctagon, Users, TrendingUp, MessageSquare, Loader, Eye, Download,
} from "lucide-react";
import { format } from "date-fns";
import html2pdf from "html2pdf.js";

type CreatorSummary = {
  username: string; total_comments: number;
  mood: string; positive_pct: number; negative_pct: number;
};
type Topic = { topic: string; count: number };

type Report = {
  id: number; campaign_id: number; title: string;
  summary?: string;
  what_worked: string[]; what_to_improve: string[]; recommendations: string[];
  metrics_snapshot: Record<string, any>;
  status: string; created_at: string;
};

const MOOD_COLOR: Record<string, string> = {
  happy:  "text-green-400",
  mixed:  "text-yellow-400",
  angry:  "text-red-400",
  neutral:"text-gray-400",
  unknown:"text-gray-500",
};

function Section({
  icon, title, color, items,
}: {
  icon: React.ReactNode; title: string; color: string; items: string[];
}) {
  if (!items?.length) return null;
  return (
    <div className="card space-y-3">
      <div className={`flex items-center gap-2 ${color}`}>
        {icon}
        <span className="font-semibold text-sm">{title}</span>
      </div>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-sm text-gray-300 leading-snug">
            <span className={`mt-0.5 shrink-0 ${color}`}>•</span>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MetricCard({ label, value, sub, color }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="card">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`text-xl font-bold mt-1 capitalize ${color ?? "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
    </div>
  );
}

function ReportDetail({ report }: { report: Report }) {
  const pdfRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownloadPdf = async () => {
    if (!pdfRef.current) return;
    setDownloading(true);
    try {
      const safeName = report.title.replace(/[^\w؀-ۿ -]+/g, "").trim() || "report";
      await html2pdf()
        .set({
          margin: 8,
          filename: `${safeName}.pdf`,
          image: { type: "jpeg", quality: 0.95 },
          html2canvas: { scale: 2, useCORS: true, backgroundColor: "#0f1117" },
          jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
          // pagebreak is a valid runtime option missing from the lib's own .d.ts
          ...( { pagebreak: { mode: ["avoid-all", "css", "legacy"] } } as object ),
        })
        .from(pdfRef.current)
        .save();
    } finally {
      setDownloading(false);
    }
  };

  const snap = report.metrics_snapshot ?? {};
  const topics: Topic[] = snap.trending_topics ?? [];
  const creators: CreatorSummary[] = snap.creator_summaries ?? [];
  const sentimentInsights: string = snap.sentiment_insights ?? "";
  const riskAlerts: string[] = snap.risk_alerts ?? [];
  const audienceInsights: string[] = snap.audience_insights ?? [];

  const pos = snap.positive_pct ?? 0;
  const neg = snap.negative_pct ?? 0;
  const neu = snap.neutral_pct ?? 0;
  const eng = snap.engagement_rate ?? 0;
  const mood = snap.audience_mood ?? "unknown";

  return (
    <div className="space-y-5">
      <div ref={pdfRef} className="space-y-5">
      {/* Header */}
      <div>
        <h2 className="font-bold text-xl">{report.title}</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Campaign #{report.campaign_id} · Generated {format(new Date(report.created_at), "MMM d, yyyy 'at' HH:mm")}
        </p>
      </div>

      {/* Executive summary */}
      {report.summary && (
        <div className="bg-brand-600/10 border border-brand-500/20 rounded-xl px-4 py-3">
          <p className="text-sm text-gray-200 leading-relaxed">{report.summary}</p>
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="Total Comments" value={(snap.total_comments ?? 0).toLocaleString()} />
        <MetricCard label="Positive" value={`${pos}%`} color="text-green-400" />
        <MetricCard label="Negative" value={`${neg}%`} color="text-red-400" />
        <MetricCard
          label="Audience Mood"
          value={mood}
          color={MOOD_COLOR[mood] ?? "text-gray-400"}
        />
      </div>

      {/* Sentiment bar */}
      <div className="space-y-1">
        <p className="text-xs text-gray-500">Sentiment breakdown</p>
        <div className="flex rounded-full overflow-hidden h-2 w-full">
          <div className="bg-green-500 transition-all" style={{ width: `${pos}%` }} />
          <div className="bg-gray-600 transition-all" style={{ width: `${neu}%` }} />
          <div className="bg-red-500 transition-all"   style={{ width: `${neg}%` }} />
        </div>
        <div className="flex gap-4 text-xs text-gray-500">
          <span className="text-green-400">{pos}% positive</span>
          <span className="text-gray-400">{neu}% neutral</span>
          <span className="text-red-400">{neg}% negative</span>
        </div>
      </div>

      {/* Sentiment insights */}
      {sentimentInsights && (
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 text-blue-400 mb-1.5">
            <Eye size={13} />
            <span className="text-xs font-semibold uppercase tracking-wide">Sentiment Insights</span>
          </div>
          <p className="text-sm text-gray-300 leading-relaxed">{sentimentInsights}</p>
        </div>
      )}

      {/* Risk alerts */}
      {riskAlerts.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 text-red-400 mb-2">
            <AlertOctagon size={13} />
            <span className="text-xs font-semibold uppercase tracking-wide">Risk Alerts</span>
          </div>
          <ul className="space-y-1.5">
            {riskAlerts.map((a, i) => (
              <li key={i} className="flex gap-2 text-sm text-gray-300">
                <span className="text-red-400 shrink-0">⚠</span> {a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 2-col grid: what worked + to improve */}
      <div className="grid sm:grid-cols-2 gap-4">
        <Section
          icon={<CheckCircle size={14} />}
          title="What Worked"
          color="text-green-400"
          items={report.what_worked}
        />
        <Section
          icon={<AlertTriangle size={14} />}
          title="To Improve"
          color="text-orange-400"
          items={report.what_to_improve}
        />
      </div>

      {/* Audience insights */}
      <Section
        icon={<Users size={14} />}
        title="Audience Insights"
        color="text-blue-400"
        items={audienceInsights}
      />

      {/* Recommendations */}
      <Section
        icon={<Lightbulb size={14} />}
        title="Recommendations"
        color="text-brand-400"
        items={report.recommendations}
      />

      {/* Creator performance */}
      {creators.length > 0 && (
        <div className="card space-y-3">
          <div className="flex items-center gap-2 text-purple-400">
            <TrendingUp size={14} />
            <span className="font-semibold text-sm">Creator Performance</span>
          </div>
          <div className="space-y-2">
            {creators.map((cr, i) => (
              <div key={cr.username} className="flex items-center gap-3">
                <span className="text-xs text-gray-600 w-4 shrink-0">#{i + 1}</span>
                <span className="text-sm font-medium w-32 truncate">@{cr.username}</span>
                <div className="flex-1 flex rounded-full overflow-hidden h-1.5">
                  <div className="bg-green-500" style={{ width: `${cr.positive_pct}%` }} />
                  <div className="bg-gray-600"  style={{ width: `${100 - cr.positive_pct - cr.negative_pct}%` }} />
                  <div className="bg-red-500"   style={{ width: `${cr.negative_pct}%` }} />
                </div>
                <span className={`text-xs w-16 text-right capitalize shrink-0 ${MOOD_COLOR[cr.mood] ?? "text-gray-400"}`}>
                  {cr.mood}
                </span>
                <span className="text-xs text-gray-500 w-20 text-right shrink-0">
                  {cr.total_comments.toLocaleString()} comments
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trending topics */}
      {topics.length > 0 && (
        <div className="card space-y-3">
          <div className="flex items-center gap-2 text-gray-400">
            <MessageSquare size={14} />
            <span className="font-semibold text-sm">Trending Topics</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {topics.slice(0, 20).map((t) => (
              <span key={t.topic} className="bg-brand-600/15 text-brand-300 text-xs px-2.5 py-1 rounded-full">
                {t.topic}
                <span className="ml-1 text-brand-500">({t.count})</span>
              </span>
            ))}
          </div>
        </div>
      )}
      </div>

      {/* Download as PDF */}
      <div className="flex justify-end pt-1">
        <button
          onClick={handleDownloadPdf}
          disabled={downloading}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          {downloading
            ? <><Loader size={14} className="animate-spin" /> Preparing PDF…</>
            : <><Download size={14} /> Download PDF</>
          }
        </button>
      </div>
    </div>
  );
}

export default function Reports() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ campaign_id: "", title: "" });
  const { data: reports = [], isLoading } = useQuery({ queryKey: ["reports"], queryFn: getReports });
  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: getCampaigns });
  const [selected, setSelected] = useState<Report | null>(null);

  const generate = useMutation({
    mutationFn: () => generateReport({
      campaign_id: parseInt(form.campaign_id),
      title: form.title,
    }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      setSelected(r);
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Reports</h1>
        <p className="text-gray-400 text-sm">AI-generated campaign performance reports</p>
      </div>

      {/* Generate form */}
      <div className="card space-y-4 max-w-lg">
        <h2 className="font-semibold">Generate Report</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Campaign</label>
            <select
              value={form.campaign_id}
              onChange={(e) => setForm({ ...form, campaign_id: e.target.value })}
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none"
            >
              <option value="">Select campaign</option>
              {campaigns.map((c: { id: number; name: string }) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Report Title</label>
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Weekly Summary"
              className="w-full bg-dark-700 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
            />
          </div>
        </div>
        <button
          onClick={() => generate.mutate()}
          disabled={!form.campaign_id || !form.title || generate.isPending}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          {generate.isPending
            ? <><Loader size={14} className="animate-spin" /> Generating…</>
            : <><FileText size={14} /> Generate Report</>
          }
        </button>
        {generate.isPending && (
          <p className="text-xs text-gray-500">Groq AI (Llama 3.3 70B) is analyzing comments, topics, and creator data — this takes ~10 seconds.</p>
        )}
      </div>

      <div className="grid lg:grid-cols-[280px_1fr] gap-6 items-start">
        {/* Report list */}
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wide font-medium px-1">All Reports</p>
          {isLoading ? (
            <p className="text-gray-400 text-sm">Loading...</p>
          ) : reports.length === 0 ? (
            <p className="text-gray-500 text-sm">No reports yet.</p>
          ) : (
            reports.map((r: Report) => (
              <button
                key={r.id}
                onClick={() => setSelected(r)}
                className={`w-full text-left card hover:border-brand-500/30 transition-colors ${selected?.id === r.id ? "border-brand-500/50 bg-brand-600/5" : ""}`}
              >
                <p className="font-medium text-sm">{r.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Campaign #{r.campaign_id} · {format(new Date(r.created_at), "MMM d, yyyy")}
                </p>
                {r.summary && (
                  <p className="text-xs text-gray-600 mt-1.5 line-clamp-2 leading-snug">{r.summary}</p>
                )}
              </button>
            ))
          )}
        </div>

        {/* Report detail */}
        {selected ? (
          <ReportDetail report={selected} />
        ) : (
          <div className="card text-center py-16 text-gray-500 text-sm">
            Select a report from the list or generate a new one.
          </div>
        )}
      </div>
    </div>
  );
}
