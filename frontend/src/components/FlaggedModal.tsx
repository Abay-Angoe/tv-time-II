import { useEffect, useState } from "react";
import { api } from "../api";
import type { FlaggedMatch, MediaType } from "../types";

interface Props {
  mediaType: MediaType;
  onClose: () => void;
  onRelink: (filmId: number, title: string) => void;
  onRemoved: () => void;
}

export default function FlaggedModal({ mediaType, onClose, onRelink, onRemoved }: Props) {
  const [items, setItems] = useState<FlaggedMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api.flagged(mediaType).then((d) => setItems(d.flagged)).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [mediaType]);

  const remove = async (f: FlaggedMatch) => {
    setBusy(f.id);
    try { await api.removeFilm(f.id); setItems((xs) => xs.filter((x) => x.id !== f.id)); onRemoved(); }
    catch { /* ignore */ } finally { setBusy(null); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal flagged-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>⚑ Review matches</h2>
        <p className="hint">Titles where the matched TMDB year differs from the year you
          logged — usually a remake/original mix-up. Re-link to the right one, or remove.</p>
        {loading && <div className="hint">Checking…</div>}
        {!loading && items.length === 0 && <div className="hint">No suspicious matches — looks clean. ✓</div>}
        <div className="flagged-list">
          {items.map((f) => (
            <div key={f.id} className="flagged-row">
              {f.poster ? <img src={f.poster} alt={f.title} /> : <div className="noposter">{f.title}</div>}
              <div className="flagged-meta">
                <div className="flagged-title">{f.title}</div>
                <div className="flagged-years">
                  matched <b>{f.matched_year}</b> · you logged <b>{f.logged_year}</b>
                </div>
              </div>
              <div className="flagged-actions">
                <button className="btn primary" disabled={busy === f.id} onClick={() => onRelink(f.id, f.title)}>Re-link</button>
                <button className="btn" disabled={busy === f.id} onClick={() => remove(f)}>Remove</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
