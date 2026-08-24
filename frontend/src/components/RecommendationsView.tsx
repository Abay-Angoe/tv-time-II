import { useEffect, useState } from "react";
import { api } from "../api";
import type { Cluster, MediaType, Recommendation } from "../types";
import { roleLabel } from "../colors";

interface Props {
  mediaType: MediaType;
  clusters: Cluster[];
  onClose: () => void;
  onAdded: (filmId: number) => void;
}

export default function RecommendationsView({ mediaType, clusters, onClose, onAdded }: Props) {
  const [scope, setScope] = useState<number | null>(null); // null = whole universe
  const [mode, setMode] = useState<"taste" | "blindspots">("taste");
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [basedOn, setBasedOn] = useState<{ name: string; role: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [added, setAdded] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.recommend(mediaType, scope, mode).then((d) => {
      if (!alive) return;
      setRecs(d.recommendations);
      setBasedOn(d.based_on);
      setLoading(false);
    }).catch(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [mediaType, scope, mode]);

  const add = async (r: Recommendation) => {
    setAdding(r.tmdb_id);
    try {
      const res = await api.add(r.tmdb_id, mediaType, true);
      setAdded((s) => new Set(s).add(r.tmdb_id));
      onAdded(res.film_id);
    } catch { /* ignore */ } finally { setAdding(null); }
  };

  const noun = mediaType === "tv" ? "shows" : "films";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal recs-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>🎯 What to watch next</h2>
        <div className="recs-tabs">
          <button className={`seg-btn ${mode === "taste" ? "on" : ""}`} onClick={() => setMode("taste")}>More like your taste</button>
          <button className={`seg-btn ${mode === "blindspots" ? "on" : ""}`} onClick={() => setMode("blindspots")}>Acclaimed blind spots</button>
        </div>
        <div className="recs-scope">
          <label>Based on</label>
          <select value={scope ?? ""} onChange={(e) => setScope(e.target.value ? +e.target.value : null)}>
            <option value="">Your whole {mediaType === "tv" ? "TV" : "movie"} taste</option>
            {clusters.filter((c) => c.id >= 0).sort((a, b) => b.size - a.size).map((c) => (
              <option key={c.id} value={c.id}>{c.label ?? `Cluster ${c.id}`} ({c.size})</option>
            ))}
          </select>
        </div>

        {basedOn.length > 0 && (
          <div className="based-on">
            {basedOn.slice(0, 8).map((b, i) => (
              <span key={i} className="based-chip">{b.name} <em>{roleLabel(b.role)}</em></span>
            ))}
          </div>
        )}

        {loading && <div className="hint">Finding {noun} you’ll like…</div>}
        {!loading && recs.length === 0 && <div className="hint">No fresh suggestions for this scope.</div>}

        <div className="recs-grid">
          {recs.map((r) => (
            <div key={r.tmdb_id} className="rec-card">
              {r.poster ? <img src={r.poster} alt={r.title} />
                : <div className="noposter">{r.title}</div>}
              {mode === "blindspots" && r.vote_average != null && (
                <span className="rec-rating">★ {r.vote_average.toFixed(1)}</span>
              )}
              <div className="rec-title">{r.title}{r.year ? ` (${r.year})` : ""}</div>
              <div className="rec-why">
                {r.reasons.slice(0, 2).map((x, i) => (
                  <span key={i} className="rec-reason">{x.name}</span>
                ))}
              </div>
              {added.has(r.tmdb_id) ? (
                <span className="added-badge">✓ added</span>
              ) : (
                <button className="btn add-btn" disabled={adding !== null} onClick={() => add(r)}>
                  {adding === r.tmdb_id ? "Adding…" : "＋ Add"}
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
