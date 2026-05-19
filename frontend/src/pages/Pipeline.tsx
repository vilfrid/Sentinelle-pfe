import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPipelineStatus, getCreatorLogs, stopCreator } from "../services/api";
import { Loader, CheckCircle, AlertCircle, Clock, RefreshCw, ChevronDown, ChevronRight, Square } from "lucide-react";
import { clsx } from "clsx";

const STATUS_COLORS: Record<string, string> = {
  idle:        "text-gray-400 bg-gray-500/10",
  discovering: "text-blue-400 bg-blue-500/10",
  scraping:    "text-yellow-400 bg-yellow-500/10",
  processing:  "text-purple-400 bg-purple-500/10",
  done:        "text-green-400 bg-green-500/10",
  error:       "text-red-400 bg-red-500/10",
};

const ETL_COLORS: Record<string, string> = {
  pending:       "bg-gray-600",
  scraped:       "bg-blue-500",
  transformed:   "bg-purple-500",
  analyzed:      "bg-green-500",
  scrape_failed: "bg-red-500",
  etl_failed:    "bg-orange-500",
};

const ACTIVE = ["discovering", "scraping", "processing"];

export default function Pipeline() {
  const { data, isLoading, dataUpdatedAt, refetch } = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: getPipelineStatus,
    refetchInterval: 3000,
  });

  if (isLoading) return <div className="text-gray-400 text-sm">Loading...</div>;

  const { stats, creators } = data;
  const active = creators.filter((c: any) => ACTIVE.includes(c.status));
  const errors = creators.filter((c: any) => c.status === "error");
  const done   = creators.filter((c: any) => c.status === "done");
  const idle   = creators.filter((c: any) => c.status === "idle");

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Pipeline Debug</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            Auto-refresh every 3s · Last update: {new Date(dataUpdatedAt).toLocaleTimeString()}
          </p>
        </div>
        <button onClick={() => refetch()}
          className="flex items-center gap-2 text-gray-400 hover:text-white text-sm px-3 py-2 rounded-lg hover:bg-white/5 transition-colors">
          <RefreshCw size={14} /> Refresh now
        </button>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Creators", value: stats.total_creators },
          { label: "Posts scraped", value: stats.total_posts },
          { label: "Comments", value: stats.total_comments },
          { label: "Active now", value: active.length, highlight: active.length > 0 },
        ].map(({ label, value, highlight }) => (
          <div key={label} className={clsx("card text-center", highlight && "border-yellow-500/30")}>
            <p className={clsx("text-2xl font-bold", highlight ? "text-yellow-400" : "text-white")}>{value}</p>
            <p className="text-gray-500 text-xs mt-1">{label}</p>
          </div>
        ))}
      </div>

      {/* Status breakdown */}
      <div className="card">
        <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-3">Status breakdown</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.by_status as Record<string, number>).map(([status, count]) => (
            <span key={status} className={clsx("flex items-center gap-1.5 text-xs px-3 py-1 rounded-full font-medium", STATUS_COLORS[status] ?? STATUS_COLORS.idle)}>
              {count}× {status}
            </span>
          ))}
          {Object.keys(stats.by_status).length === 0 && (
            <span className="text-gray-500 text-sm">No creators yet</span>
          )}
        </div>
      </div>

      {/* Active pipelines */}
      {active.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-medium">Running now</p>
          {active.map((c: any) => <CreatorRow key={c.id} creator={c} />)}
        </section>
      )}

      {/* Errors */}
      {errors.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs text-red-400 uppercase tracking-wider font-medium">Errors</p>
          {errors.map((c: any) => <CreatorRow key={c.id} creator={c} />)}
        </section>
      )}

      {/* Done */}
      {done.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-medium">Completed</p>
          {done.map((c: any) => <CreatorRow key={c.id} creator={c} />)}
        </section>
      )}

      {/* Idle */}
      {idle.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-medium">Idle</p>
          {idle.map((c: any) => <CreatorRow key={c.id} creator={c} />)}
        </section>
      )}

      {creators.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-400">No creators tracked yet.</p>
        </div>
      )}
    </div>
  );
}

const STATUS_ICON: Record<string, string> = {
  ok: "text-green-400", info: "text-blue-400", warn: "text-yellow-400", error: "text-red-400",
};
const STEP_LABEL: Record<string, string> = {
  init: "INIT", discover: "DISCOVER", scrape: "SCRAPE",
  etl: "ETL", arabizi: "ARABIZI", sentiment: "SENTIMENT", finalize: "FINALIZE",
};

function CreatorRow({ creator }: { creator: any }) {
  const isActive = ACTIVE.includes(creator.status);
  const [open, setOpen] = useState(isActive);
  const qc = useQueryClient();

  const { data: logs = [] } = useQuery({
    queryKey: ["creator-logs", creator.id],
    queryFn: () => getCreatorLogs(creator.id),
    refetchInterval: isActive ? 2000 : false,
    enabled: open,
  });

  const stop = useMutation({
    mutationFn: () => stopCreator(creator.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline-status"] });
      qc.invalidateQueries({ queryKey: ["creator-logs", creator.id] });
    },
  });

  return (
    <div className="card space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isActive && <Loader size={14} className="animate-spin text-yellow-400 shrink-0" />}
          {creator.status === "done"  && <CheckCircle size={14} className="text-green-400 shrink-0" />}
          {creator.status === "error" && <AlertCircle size={14} className="text-red-400 shrink-0" />}
          {creator.status === "idle"  && <Clock size={14} className="text-gray-500 shrink-0" />}
          <div>
            <span className="font-medium text-sm">@{creator.username}</span>
            <span className="text-gray-500 text-xs ml-2">{creator.platform}</span>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span>{creator.total_posts} posts</span>
          <span>{creator.total_comments} comments</span>
          {creator.last_run && <span>{new Date(creator.last_run).toLocaleTimeString()}</span>}
          <span className={clsx("px-2 py-0.5 rounded-full font-medium", STATUS_COLORS[creator.status] ?? STATUS_COLORS.idle)}>
            {creator.status}
          </span>
          {isActive && (
            <button
              onClick={() => stop.mutate()}
              disabled={stop.isPending}
              title="Stop scraping"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-400 disabled:opacity-50 transition-colors border border-yellow-500/20 font-medium">
              <Square size={11} />
              Stop
            </button>
          )}
          <button onClick={() => setOpen(!open)}
            className="text-gray-500 hover:text-white transition-colors ml-1">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        </div>
      </div>

      {/* ETL breakdown */}
      {Object.keys(creator.etl_breakdown).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(creator.etl_breakdown as Record<string, number>).map(([status, count]) => (
            <span key={status} className="flex items-center gap-1.5 text-xs text-gray-400">
              <span className={clsx("w-2 h-2 rounded-full inline-block", ETL_COLORS[status] ?? "bg-gray-500")} />
              {count} {status}
            </span>
          ))}
        </div>
      )}

      {/* Error */}
      {creator.error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-red-300 font-mono break-all">
          {creator.error}
        </div>
      )}

      {/* Log panel */}
      {open && (
        <div className="bg-dark-900 rounded-lg border border-white/5 overflow-hidden">
          <div className="px-3 py-2 border-b border-white/5 flex items-center justify-between">
            <span className="text-xs text-gray-500 font-medium uppercase tracking-wider">Pipeline log</span>
            {creator.task_id && (
              <span className="text-xs text-gray-700 font-mono">{creator.task_id.slice(0, 8)}</span>
            )}
          </div>
          <div className="max-h-72 overflow-y-auto p-3 space-y-1 font-mono text-xs">
            {logs.length === 0 ? (
              <p className="text-gray-600">No logs yet — trigger the pipeline first.</p>
            ) : (
              [...logs].reverse().map((log: any, i: number) => (
                <div key={i} className="flex gap-2 leading-relaxed">
                  <span className="text-gray-600 shrink-0">
                    {new Date(log.ts).toLocaleTimeString()}
                  </span>
                  <span className={clsx("shrink-0 w-16 uppercase", STATUS_ICON[log.status] ?? "text-gray-400")}>
                    [{STEP_LABEL[log.step] ?? log.step}]
                  </span>
                  <span className={clsx(
                    log.status === "error" ? "text-red-300" :
                    log.status === "warn"  ? "text-yellow-300" :
                    log.status === "ok"    ? "text-green-300" : "text-gray-300"
                  )}>
                    {log.msg}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
