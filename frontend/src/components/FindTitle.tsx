import { useMemo, useState } from "react";
import type { GraphNode } from "../types";

interface Props {
  nodes: GraphNode[];
  onPick: (id: number) => void;
}

export default function FindTitle({ nodes, onPick }: Props) {
  const [q, setQ] = useState("");

  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return nodes
      .filter((n) => n.title.toLowerCase().includes(s))
      .sort((a, b) => a.title.localeCompare(b.title))
      .slice(0, 10);
  }, [q, nodes]);

  const pick = (id: number) => { onPick(id); setQ(""); };

  return (
    <div className="find-title">
      <input
        className="find-input"
        placeholder="🔎 Find a title…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) pick(matches[0].id); }}
      />
      {matches.length > 0 && (
        <div className="find-results">
          {matches.map((n) => (
            <button key={n.id} className="find-item" onClick={() => pick(n.id)}>
              {n.title}{n.year ? ` (${n.year})` : ""}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
