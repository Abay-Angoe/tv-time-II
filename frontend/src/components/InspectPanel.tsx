import { useEffect, useState } from "react";
import { api } from "../api";
import type { FilmDetail, ListSummary, MediaType, Theme, Twin } from "../types";
import { edgeTypeColor, roleLabel } from "../colors";

interface Props {
  filmId: number;
  onSelect: (id: number) => void;
  onPathFrom: (id: number) => void;
  onThemeClick: (theme: Theme) => void;
  onPersonClick: (personId: number) => void;
  onFilmUpdated: (id: number, patch: { watched: boolean; rewatches: number }) => void;
  onCrossSelect: (mediaType: MediaType, id: number) => void;
  onCompare: (id: number) => void;
  onRelink: (id: number, title: string) => void;
  onRemoved: (id: number) => void;
  lists: ListSummary[];
  onListsChanged: () => void;
  onClose: () => void;
}

export default function InspectPanel({ filmId, onSelect, onPathFrom, onThemeClick, onPersonClick, onFilmUpdated, onCrossSelect, onCompare, onRelink, onRemoved, lists, onListsChanged, onClose }: Props) {
  const [film, setFilm] = useState<FilmDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [twins, setTwins] = useState<Twin[]>([]);
  const [memberOf, setMemberOf] = useState<Set<number>>(new Set());

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setTwins([]);
    setMemberOf(new Set());
    api.film(filmId).then((f) => { if (alive) { setFilm(f); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    api.twins(filmId).then((t) => { if (alive) setTwins(t.twins); }).catch(() => {});
    api.filmLists(filmId).then((r) => { if (alive) setMemberOf(new Set(r.list_ids)); }).catch(() => {});
    return () => { alive = false; };
  }, [filmId]);

  const toggleList = async (listId: number) => {
    if (!film) return;
    const isMember = memberOf.has(listId);
    setMemberOf((s) => { const n = new Set(s); isMember ? n.delete(listId) : n.add(listId); return n; });
    try {
      if (isMember) await api.removeFromList(listId, film.id);
      else await api.addToList(listId, film.id);
      onListsChanged();
    } catch { /* ignore */ }
  };

  const markWatched = async () => {
    if (!film) return;
    setBusy(true);
    try {
      const r = await api.setWatched(film.id, true);
      setFilm({ ...film, watched: r.watched, rewatches: r.rewatches });
      onFilmUpdated(film.id, { watched: r.watched, rewatches: r.rewatches });
    } catch { /* ignore */ } finally { setBusy(false); }
  };

  const rewatch = async () => {
    if (!film) return;
    setBusy(true);
    try {
      const r = await api.logRewatch(film.id);
      setFilm({ ...film, watched: r.watched, rewatches: r.rewatches });
      onFilmUpdated(film.id, { watched: r.watched, rewatches: r.rewatches });
    } catch { /* ignore */ } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!film || !confirm(`Remove "${film.title}" from your collection?`)) return;
    setBusy(true);
    try { await api.removeFilm(film.id); onRemoved(film.id); }
    catch { setBusy(false); }
  };

  if (loading) return <div className="panel inspect"><div className="hint">Loading…</div></div>;
  if (!film) return <div className="panel inspect"><div className="hint">Film not found.</div></div>;

  return (
    <div className="panel inspect">
      <button className="close" onClick={onClose}>×</button>
      <div className="film-head">
        {film.poster && <img src={film.poster} alt={film.title} className="poster" />}
        <div>
          <h2>{film.title}</h2>
          <div className="meta">
            {film.media_type === "tv" ? "📺 Series" : "🎬 Film"} · {film.year ?? "—"}
            {film.runtime ? ` · ${film.runtime} min` : ""}
            {film.rating != null ? ` · ★ ${film.rating}` : ""}
            {film.media_type === "tv" && (
              <span className={`watch-badge ${film.watched ? "seen" : "unseen"}`}>
                {film.watched ? "watched" : "followed · unwatched"}
              </span>
            )}
          </div>
          {film.cluster?.label && (
            <div className="cluster-tag">{film.cluster.label}</div>
          )}
          {film.tagline && <div className="tagline">“{film.tagline}”</div>}
        </div>
      </div>

      <div className="watch-actions">
        {!film.watched ? (
          <button className="btn primary" disabled={busy} onClick={markWatched}>
            {busy ? "…" : "✓ Mark as watched"}
          </button>
        ) : (
          <button className="btn" disabled={busy} onClick={rewatch}>
            {busy ? "…" : `＋ Log a rewatch${film.rewatches ? ` · ${film.rewatches}×` : ""}`}
          </button>
        )}
      </div>

      {film.overview && <p className="overview">{film.overview}</p>}

      {film.genres.length > 0 && (
        <div className="genres">{film.genres.map((g) => <span key={g} className="genre">{g}</span>)}</div>
      )}

      {film.themes.length > 0 && (
        <div className="themes">
          <span className="themes-label">{film.themes_source === "llm" ? "Themes ✨" : "Themes"}</span>
          {film.themes.map((t) => (
            <button key={t.name} className="theme-chip" onClick={() => onThemeClick(t)}
                    title={`Highlight everything tagged “${t.name}”`}>
              {t.name}
            </button>
          ))}
        </div>
      )}

      {lists.length > 0 && (
        <div className="film-lists">
          <span className="themes-label">Lists</span>
          {lists.map((l) => (
            <button key={l.id} className={`list-chip ${memberOf.has(l.id) ? "on" : ""}`}
                    onClick={() => toggleList(l.id)}>
              {memberOf.has(l.id) ? "✓ " : "＋ "}{l.name}
            </button>
          ))}
        </div>
      )}

      <div className="row-btns">
        <button className="btn" onClick={() => onPathFrom(film.id)}>Path from here →</button>
        <button className="btn" onClick={() => onCompare(film.id)}>Compare ⇄</button>
      </div>
      <div className="fix-row">
        <button className="link-btn" onClick={() => onRelink(film.id, film.title)}>Wrong match?</button>
        <span className="dot-sep">·</span>
        <button className="link-btn danger" onClick={remove} disabled={busy}>Remove</button>
      </div>

      <section>
        <h3>Strongest creative connections</h3>
        {film.connections.length === 0 && <div className="hint">No strong connections at current data.</div>}
        <ul className="conn-list">
          {film.connections.map((c) => (
            <li key={c.film.id}>
              <button className="conn" onClick={() => onSelect(c.film.id)}>
                <span className="conn-title">{c.film.title} {c.film.year ? `(${c.film.year})` : ""}</span>
                <span className="conn-weight">{(c.weight * 100).toFixed(0)}%</span>
              </button>
              <div className="factors">
                {c.factors.slice(0, 4).map((f, i) => (
                  <span key={i} className="factor" style={{ borderColor: edgeTypeColor(f.type) }}>
                    <b>{roleLabel(f.type)}:</b> {f.detail}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {twins.length > 0 && (
        <section>
          <h3>{film.media_type === "tv" ? "Its movie twins" : "Its TV twins"}</h3>
          <div className="neighbors">
            {twins.map((t) => (
              <button key={t.id} className="neighbor twin" onClick={() => onCrossSelect(t.media_type, t.id)}
                      title={`${(t.similarity * 100).toFixed(0)}% similar${t.cluster ? ` · ${t.cluster}` : ""}`}>
                {t.poster ? <img src={t.poster} alt={t.title} /> : <div className="noposter">{t.title}</div>}
                <span className="twin-cap">{t.media_type === "tv" ? "📺" : "🎬"} {t.title}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section>
        <h3>Nearest in theme space</h3>
        <div className="neighbors">
          {film.neighbors.map((n) => (
            <button key={n.id} className="neighbor" onClick={() => onSelect(n.id)} title={`${(n.similarity * 100).toFixed(0)}% similar`}>
              {n.poster ? <img src={n.poster} alt={n.title} /> : <div className="noposter">{n.title}</div>}
            </button>
          ))}
        </div>
      </section>

      {Object.keys(film.credits).length > 0 && (
        <section>
          <h3>Credits</h3>
          {Object.entries(film.credits).map(([role, people]) => (
            <div key={role} className="credit-row">
              <span className="credit-role">{roleLabel(role)}</span>
              <span className="credit-names">
                {people.map((p, i) => (
                  <span key={p.id}>
                    {i > 0 && ", "}
                    <button className="person-link" onClick={() => onPersonClick(p.id)}>{p.name}</button>
                  </span>
                ))}
              </span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
