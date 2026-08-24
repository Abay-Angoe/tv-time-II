import { useState } from "react";
import { api } from "../api";
import type { GraphNode, PathResult } from "../types";
import { roleLabel } from "../colors";

interface Props {
  nodes: GraphNode[];
  fromId: number | null;
  onFrom: (id: number | null) => void;
  onResult: (r: PathResult | null) => void;
  onSelect: (id: number) => void;
}

export default function Pathfinder({ nodes, fromId, onFrom, onResult, onSelect }: Props) {
  const [toId, setToId] = useState<number | null>(null);
  const [result, setResult] = useState<PathResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (fromId == null || toId == null) return;
    setBusy(true); setError(null);
    try {
      const r = await api.path(fromId, toId);
      setResult(r);
      onResult(r);
      if (!r.connected) setError("No connection through shared cast/crew.");
    } catch {
      setError("Pathfinding failed.");
    } finally {
      setBusy(false);
    }
  };

  const clear = () => { setResult(null); onResult(null); setError(null); };

  return (
    <div className="panel pathfinder">
      <h3>Six degrees</h3>
      <FilmSelect nodes={nodes} value={fromId} onChange={onFrom} placeholder="From film…" />
      <FilmSelect nodes={nodes} value={toId} onChange={setToId} placeholder="To film…" />
      <div className="row-btns">
        <button className="btn primary" disabled={fromId == null || toId == null || busy} onClick={run}>
          {busy ? "Finding…" : "Find path"}
        </button>
        <button className="btn" onClick={clear}>Clear</button>
      </div>
      {error && <div className="hint warn">{error}</div>}
      {result?.connected && (
        <div className="chain">
          <div className="degrees">{result.degrees} degree{result.degrees === 1 ? "" : "s"} of separation</div>
          {result.chain.map((link, i) => (
            <div key={i} className="chain-link">
              <button className="link-film" onClick={() => onSelect(link.from.id)}>{link.from.title}</button>
              <div className="via">
                {link.via.map((v, j) => (
                  <span key={j} className="via-item">↓ {v.person} <em>({roleLabel(v.role)})</em></span>
                ))}
              </div>
              {i === result.chain.length - 1 && (
                <button className="link-film" onClick={() => onSelect(link.to.id)}>{link.to.title}</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FilmSelect({ nodes, value, onChange, placeholder }: {
  nodes: GraphNode[];
  value: number | null;
  onChange: (id: number | null) => void;
  placeholder: string;
}) {
  const sorted = [...nodes].sort((a, b) => a.title.localeCompare(b.title));
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? +e.target.value : null)}>
      <option value="">{placeholder}</option>
      {sorted.map((n) => (
        <option key={n.id} value={n.id}>{n.title}{n.year ? ` (${n.year})` : ""}</option>
      ))}
    </select>
  );
}
