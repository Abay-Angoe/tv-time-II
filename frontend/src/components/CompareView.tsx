import { useEffect, useState } from "react";
import { api } from "../api";
import type { CompareResult, GraphNode } from "../types";
import { roleLabel } from "../colors";

interface Props {
  nodes: GraphNode[];
  initialA: number | null;
  onClose: () => void;
  onSelect: (id: number) => void;
}

export default function CompareView({ nodes, initialA, onClose, onSelect }: Props) {
  const [a, setA] = useState<number | null>(initialA);
  const [b, setB] = useState<number | null>(null);
  const [data, setData] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const sorted = [...nodes].sort((x, y) => x.title.localeCompare(y.title));

  useEffect(() => {
    if (a == null || b == null || a === b) { setData(null); return; }
    let alive = true;
    setLoading(true);
    api.compare(a, b).then((d) => alive && setData(d)).catch(() => {}).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [a, b]);

  const sel = (val: number | null, on: (v: number | null) => void, ph: string) => (
    <select value={val ?? ""} onChange={(e) => on(e.target.value ? +e.target.value : null)}>
      <option value="">{ph}</option>
      {sorted.map((n) => <option key={n.id} value={n.id}>{n.title}{n.year ? ` (${n.year})` : ""}</option>)}
    </select>
  );

  const pct = data?.cosine != null ? Math.round(data.cosine * 100) : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal compare-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>×</button>
        <h2>Compare two titles</h2>
        <div className="cmp-pickers">{sel(a, setA, "First title…")}<span className="cmp-vs">vs</span>{sel(b, setB, "Second title…")}</div>

        {loading && <div className="hint">Comparing…</div>}
        {data && (
          <>
            <div className="cmp-heads">
              {[data.a, data.b].map((f, i) => (
                <button key={i} className="cmp-head" onClick={() => onSelect(f.id)}>
                  {f.poster ? <img src={f.poster} alt={f.title} /> : <div className="noposter">{f.title}</div>}
                  <div className="cmp-title">{f.title}{f.year ? ` (${f.year})` : ""}</div>
                  {f.cluster && <div className="cmp-cluster">{f.cluster}</div>}
                </button>
              ))}
            </div>

            {pct != null && (
              <div className="cmp-sim">
                <div className="cmp-sim-label">Thematic similarity <b>{pct}%</b>
                  {!data.same_universe && <span className="cmp-cross"> · cross-universe</span>}
                </div>
                <div className="cmp-bar"><div className="cmp-bar-fill" style={{ width: `${pct}%` }} /></div>
              </div>
            )}

            <div className="cmp-shared">
              {data.shared_collection && (
                <Row label="Franchise"><span className="cmp-chip strong">{data.shared_collection}</span></Row>
              )}
              {data.shared_people.length > 0 && (
                <Row label="Shared people">
                  {data.shared_people.map((p) => (
                    <span key={p.id} className="cmp-chip">{p.name} <em>{p.roles.map(roleLabel).join("/")}</em></span>
                  ))}
                </Row>
              )}
              {data.shared_keywords.length > 0 && (
                <Row label="Shared themes">
                  {data.shared_keywords.slice(0, 12).map((k) => <span key={k} className="cmp-chip">{k}</span>)}
                </Row>
              )}
              {data.shared_genres.length > 0 && (
                <Row label="Shared genres">
                  {data.shared_genres.map((g) => <span key={g} className="cmp-chip">{g}</span>)}
                </Row>
              )}
              {!data.shared_collection && data.shared_people.length === 0 &&
                data.shared_keywords.length === 0 && data.shared_genres.length === 0 && (
                <div className="hint">No shared attributes — they're linked only by theme (position).</div>
              )}
            </div>

            {data.edge && (
              <div className="cmp-edge">Direct creative edge: <b>{Math.round(data.edge.weight * 100)}%</b> strength</div>
            )}

            {data.same_universe && (
              <div className="cmp-path">
                <h3>Six degrees</h3>
                {data.path && data.path.length > 0 ? (
                  <div className="chain">
                    {data.path.map((l, i) => (
                      <div key={i} className="chain-link">
                        <button className="link-film" onClick={() => onSelect(l.from.id)}>{l.from.title}</button>
                        <div className="via">{l.via.map((v, j) => (
                          <span key={j} className="via-item">↓ {v.person} <em>({roleLabel(v.role)})</em></span>))}</div>
                        {i === data.path!.length - 1 && (
                          <button className="link-film" onClick={() => onSelect(l.to.id)}>{l.to.title}</button>)}
                      </div>
                    ))}
                  </div>
                ) : data.path && data.path.length === 0 ? (
                  <div className="hint">Same film.</div>
                ) : (
                  <div className="hint">No cast/crew path between them.</div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="cmp-row">
      <span className="cmp-row-label">{label}</span>
      <div className="cmp-row-vals">{children}</div>
    </div>
  );
}
