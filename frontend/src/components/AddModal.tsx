import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MediaType, SearchResult } from "../types";

interface Props {
  mediaType: MediaType;
  onClose: () => void;
  onAdded: (filmId: number) => void;
}

export default function AddModal({ mediaType, onClose, onAdded }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [watched, setWatched] = useState(true);
  const [adding, setAdding] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!q.trim()) { setResults([]); return; }
    timer.current = setTimeout(async () => {
      setSearching(true); setError(null);
      try {
        const { results } = await api.search(q, mediaType);
        setResults(results);
      } catch {
        setError("Search failed. Is the backend running with a TMDB key?");
      } finally {
        setSearching(false);
      }
    }, 350);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [q, mediaType]);

  const add = async (r: SearchResult) => {
    setAdding(r.tmdb_id); setError(null);
    try {
      const res = await api.add(r.tmdb_id, mediaType, mediaType === "tv" ? watched : true);
      onAdded(res.film_id);
    } catch {
      setError(`Couldn’t add “${r.title}”.`);
      setAdding(null);
    }
  };

  const noun = mediaType === "tv" ? "show" : "film";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal add-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>＋ Add a {noun}</h2>
        <p className="hint">Searches TMDB · adds into your current {mediaType === "tv" ? "TV" : "movie"} map.</p>

        <input
          autoFocus
          className="add-search"
          placeholder={`Search for a ${noun}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />

        {mediaType === "tv" && (
          <label className="watched-toggle">
            <input type="checkbox" checked={watched} onChange={(e) => setWatched(e.target.checked)} />
            Mark as watched (uncheck for “followed / to-watch”)
          </label>
        )}

        {error && <div className="hint warn">{error}</div>}
        {searching && <div className="hint">Searching…</div>}

        <div className="add-results">
          {results.map((r) => (
            <div key={r.tmdb_id} className="add-result">
              {r.poster
                ? <img src={r.poster} alt={r.title} />
                : <div className="noposter">{r.title}</div>}
              <div className="add-meta">
                <div className="add-title">{r.title} {r.year ? <span className="add-year">({r.year})</span> : null}</div>
                {r.overview && <div className="add-overview">{r.overview}</div>}
              </div>
              {r.already_added ? (
                <span className="added-badge">✓ in map</span>
              ) : (
                <button className="btn primary add-btn" disabled={adding !== null} onClick={() => add(r)}>
                  {adding === r.tmdb_id ? "Adding…" : "Add"}
                </button>
              )}
            </div>
          ))}
          {!searching && q.trim() && results.length === 0 && (
            <div className="hint">No matches.</div>
          )}
        </div>
      </div>
    </div>
  );
}
