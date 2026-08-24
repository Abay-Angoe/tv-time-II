import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MediaType, SearchResult } from "../types";

interface Props {
  filmId: number;
  mediaType: MediaType;
  initialQuery: string;
  onDone: (newFilmId: number) => void;
  onClose: () => void;
}

export default function RelinkModal({ filmId, mediaType, initialQuery, onDone, onClose }: Props) {
  const [q, setQ] = useState(initialQuery);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [linking, setLinking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!q.trim()) { setResults([]); return; }
    timer.current = setTimeout(async () => {
      setSearching(true); setError(null);
      try { setResults((await api.search(q, mediaType)).results); }
      catch { setError("Search failed."); }
      finally { setSearching(false); }
    }, 350);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [q, mediaType]);

  const pick = async (r: SearchResult) => {
    setLinking(r.tmdb_id); setError(null);
    try { onDone((await api.relink(filmId, r.tmdb_id)).film_id); }
    catch { setError(`Couldn't re-link to "${r.title}".`); setLinking(null); }
  };

  const noun = mediaType === "tv" ? "show" : "film";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal add-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>Re-link to the correct {noun}</h2>
        <p className="hint">Pick the right TMDB entry (e.g. the right year/version). Your
          watched status, rewatches and list memberships carry over.</p>
        <input autoFocus className="add-search" placeholder={`Search ${noun}s…`}
               value={q} onChange={(e) => setQ(e.target.value)} />
        {error && <div className="hint warn">{error}</div>}
        {searching && <div className="hint">Searching…</div>}
        <div className="add-results">
          {results.map((r) => (
            <div key={r.tmdb_id} className="add-result">
              {r.poster ? <img src={r.poster} alt={r.title} /> : <div className="noposter">{r.title}</div>}
              <div className="add-meta">
                <div className="add-title">{r.title} {r.year ? <span className="add-year">({r.year})</span> : null}</div>
                {r.overview && <div className="add-overview">{r.overview}</div>}
              </div>
              <button className="btn primary add-btn" disabled={linking !== null} onClick={() => pick(r)}>
                {linking === r.tmdb_id ? "Linking…" : "Use this"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
