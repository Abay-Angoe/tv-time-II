import { useEffect, useState } from "react";
import { api } from "../api";
import type { Analytics, MediaType } from "../types";
import { roleLabel } from "../colors";

interface Props {
  mediaType: MediaType;
  onClose: () => void;
  onSelect: (id: number) => void;
}

const ACCENT = "#56b4e9";

/** Horizontal labelled bar row. */
function Bar({ label, value, max, suffix }: { label: string; value: number; max: number; suffix?: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="bar-row">
      <span className="bar-label" title={label}>{label}</span>
      <span className="bar-track"><span className="bar-fill" style={{ width: `${pct}%` }} /></span>
      <span className="bar-val">{value}{suffix ?? ""}</span>
    </div>
  );
}

export default function AnalyticsView({ mediaType, onClose, onSelect }: Props) {
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    api.analytics(mediaType).then((d) => alive && setData(d)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [mediaType]);

  const noun = mediaType === "tv" ? "shows" : "films";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wrapped" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>✨ Your {mediaType === "tv" ? "TV" : "Cinema"} Wrapped</h2>

        {error && <div className="hint warn">Couldn’t load analytics.</div>}
        {!data && !error && <div className="hint">Crunching…</div>}

        {data && (
          <>
            <div className="stat-row">
              <Stat n={data.totals.titles} label={noun} />
              {mediaType === "tv" && <Stat n={data.totals.watched} label="watched" />}
              <Stat n={data.totals.runtime_hours} label="hours watched" />
              <Stat n={data.totals.runtime_days} label="days watched" />
            </div>

            <div className="wrapped-grid">
              <section className="card">
                <h3>By decade</h3>
                {data.by_decade.map((d) => (
                  <Bar key={d.decade} label={`${d.decade}s`} value={d.count}
                       max={Math.max(...data.by_decade.map((x) => x.count))} />
                ))}
              </section>

              {data.by_watch_year.length > 0 && (
                <section className="card">
                  <h3>Watch timeline</h3>
                  {data.by_watch_year.map((d) => (
                    <Bar key={d.year} label={`${d.year}`} value={d.count}
                         max={Math.max(...data.by_watch_year.map((x) => x.count))} />
                  ))}
                </section>
              )}

              <section className="card">
                <h3>Top genres</h3>
                {data.top_genres.map((g) => (
                  <Bar key={g.name} label={g.name} value={g.count}
                       max={Math.max(...data.top_genres.map((x) => x.count))} />
                ))}
              </section>

              <section className="card">
                <h3>Biggest phases</h3>
                {data.phases.map((p, i) => (
                  <Bar key={i} label={p.label ?? "—"} value={p.size}
                       max={Math.max(...data.phases.map((x) => x.size))} />
                ))}
              </section>

              <section className="card wide">
                <h3>Recurring collaborators</h3>
                <div className="collab-grid">
                  {Object.entries(data.collaborators).map(([role, people]) => (
                    <div key={role} className="collab-col">
                      <h4>{roleLabel(role)}</h4>
                      {people.map((p) => (
                        <div key={p.name} className="collab-item">
                          <span>{p.name}</span><span className="collab-count">{p.count}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </section>

              <section className="card wide">
                <h3>Most-connected {noun}</h3>
                <div className="hub-row">
                  {data.hubs.map((h) => (
                    <button key={h.id} className="hub" onClick={() => { onSelect(h.id); onClose(); }}
                            title={`connection score ${h.score}`}>
                      {h.poster ? <img src={h.poster} alt={h.title} /> :
                        <div className="noposter">{h.title}</div>}
                      <span className="hub-title">{h.title}</span>
                    </button>
                  ))}
                </div>
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  );

  function Stat({ n, label }: { n: number; label: string }) {
    return (
      <div className="big-stat">
        <span className="big-num" style={{ color: ACCENT }}>{n.toLocaleString()}</span>
        <span className="big-label">{label}</span>
      </div>
    );
  }
}
