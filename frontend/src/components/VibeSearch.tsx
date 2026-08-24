import { useState } from "react";
import { api } from "../api";
import type { MediaType, VibeResult } from "../types";

interface Props {
  mediaType: MediaType;
  onHighlight: (hl: { label: string; ids: Set<number> } | null) => void;
  onPick: (id: number) => void;
}

export default function VibeSearch({ mediaType, onHighlight, onPick }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<VibeResult[]>([]);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!q.trim()) return;
    setLoading(true);
    try {
      const { results } = await api.vibe(q, mediaType);
      setResults(results);
      onHighlight({ label: `vibe: "${q.trim()}"`, ids: new Set(results.map((r) => r.id)) });
      if (results[0]) onPick(results[0].id);
    } catch { /* ignore */ } finally { setLoading(false); }
  };

  const clear = () => { setQ(""); setResults([]); onHighlight(null); };

  return (
    <div className="panel vibe">
      <h3>Vibe search</h3>
      <input
        className="vibe-input"
        placeholder="a mood… “neon loneliness”"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") run(); }}
      />
      <div className="row-btns">
        <button className="btn primary" onClick={run} disabled={loading || !q.trim()}>
          {loading ? "…" : "Search"}
        </button>
        {results.length > 0 && <button className="btn" onClick={clear}>Clear</button>}
      </div>
      {results.length > 0 && (
        <div className="vibe-results">
          {results.slice(0, 10).map((r) => (
            <button key={r.id} className="vibe-item" onClick={() => onPick(r.id)}>
              <span className="vibe-title">{r.title}{r.year ? ` (${r.year})` : ""}</span>
              <span className="vibe-score">{Math.round(r.score * 100)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
