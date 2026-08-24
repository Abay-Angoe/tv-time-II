import type { AppConfig, MediaType } from "../types";
import { edgeTypeColor, roleLabel } from "../colors";

export type WatchedFilter = "all" | "watched" | "unwatched";

export interface Filters {
  decade: number | null;
  minRating: number;
  clusterId: number | null;
  watched: WatchedFilter;
}

interface Props {
  config: AppConfig;
  mediaType: MediaType;
  threshold: number;
  onThreshold: (v: number) => void;
  edgeTypes: string[];
  enabledTypes: Set<string>;
  onToggleType: (t: string) => void;
  showEdges: boolean;
  onToggleEdges: (v: boolean) => void;
  filters: Filters;
  onFilters: (f: Filters) => void;
  decades: number[];
  clusters: { id: number; label: string | null }[];
  edgeCount: number;
  onSurprise: () => void;
}

export default function Controls(props: Props) {
  const {
    mediaType, threshold, onThreshold, edgeTypes, enabledTypes, onToggleType,
    showEdges, onToggleEdges, filters, onFilters, decades, clusters,
    edgeCount, onSurprise,
  } = props;

  return (
    <div className="panel controls">
      <h2>Explore</h2>

      <section>
        <label className="row">
          <span>Resolution of your taste</span>
          <span className="mono">{threshold.toFixed(2)}</span>
        </label>
        <input
          type="range" min={0} max={1} step={0.01}
          value={threshold}
          onChange={(e) => onThreshold(parseFloat(e.target.value))}
        />
        <div className="hint">{edgeCount} connections drawn · higher = tighter constellations</div>
      </section>

      <section>
        <label className="row">
          <span>Creative connections</span>
          <input type="checkbox" checked={showEdges} onChange={(e) => onToggleEdges(e.target.checked)} />
        </label>
        <div className="chips">
          {edgeTypes.map((t) => {
            const on = enabledTypes.has(t);
            return (
              <button
                key={t}
                className={`chip ${on ? "on" : ""}`}
                onClick={() => onToggleType(t)}
                style={on ? { borderColor: edgeTypeColor(t), color: edgeTypeColor(t) } : undefined}
                disabled={!showEdges}
              >
                <span className="dot" style={{ background: edgeTypeColor(t) }} />
                {roleLabel(t)}
              </button>
            );
          })}
        </div>
      </section>

      <section>
        <label className="row"><span>Filters</span></label>
        {mediaType === "tv" && (
          <div className="field">
            <label>Watch status</label>
            <div className="seg">
              {(["all", "watched", "unwatched"] as const).map((w) => (
                <button
                  key={w}
                  className={`seg-btn ${filters.watched === w ? "on" : ""}`}
                  onClick={() => onFilters({ ...filters, watched: w })}
                >
                  {w[0].toUpperCase() + w.slice(1)}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="field">
          <label>Decade</label>
          <select
            value={filters.decade ?? ""}
            onChange={(e) => onFilters({ ...filters, decade: e.target.value ? +e.target.value : null })}
          >
            <option value="">All</option>
            {decades.map((d) => <option key={d} value={d}>{d}s</option>)}
          </select>
        </div>
        <div className="field">
          <label>Min rating {filters.minRating > 0 ? `≥ ${filters.minRating}` : ""}</label>
          <input
            type="range" min={0} max={10} step={1}
            value={filters.minRating}
            onChange={(e) => onFilters({ ...filters, minRating: +e.target.value })}
          />
        </div>
        <div className="field">
          <label>Cluster</label>
          <select
            value={filters.clusterId ?? ""}
            onChange={(e) => onFilters({ ...filters, clusterId: e.target.value ? +e.target.value : null })}
          >
            <option value="">All</option>
            {clusters.map((c) => <option key={c.id} value={c.id}>{c.label ?? `Cluster ${c.id}`}</option>)}
          </select>
        </div>
      </section>

      <button className="btn primary" onClick={onSurprise}>✨ Surprise me</button>
    </div>
  );
}
