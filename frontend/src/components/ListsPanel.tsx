import { useState } from "react";
import { api } from "../api";
import type { ListSummary } from "../types";

interface Props {
  lists: ListSummary[];
  nodeIds: Set<number>;          // current-universe node ids (to intersect for highlight)
  activeListId: number | null;
  onReload: () => void;
  onHighlight: (hl: { label: string; ids: Set<number> } | null, listId: number | null) => void;
}

export default function ListsPanel({ lists, nodeIds, activeListId, onReload, onHighlight }: Props) {
  const [name, setName] = useState("");

  const create = async () => {
    if (!name.trim()) return;
    await api.createList(name.trim());
    setName("");
    onReload();
  };

  const show = async (l: ListSummary) => {
    if (activeListId === l.id) { onHighlight(null, null); return; }
    const d = await api.listDetail(l.id);
    const ids = new Set(d.film_ids.filter((id) => nodeIds.has(id)));
    onHighlight({ label: `list: ${l.name}`, ids }, l.id);
  };

  const remove = async (l: ListSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    if (activeListId === l.id) onHighlight(null, null);
    await api.deleteList(l.id);
    onReload();
  };

  return (
    <div className="panel lists-panel">
      <h3>Lists</h3>
      <div className="new-list">
        <input
          placeholder="New list… (e.g. comfort films)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") create(); }}
        />
        <button className="btn" onClick={create} disabled={!name.trim()}>+</button>
      </div>
      {lists.length === 0 && <div className="hint">No lists yet. Create one, then add titles from their panel.</div>}
      <div className="list-rows">
        {lists.map((l) => (
          <div key={l.id} className={`list-row ${activeListId === l.id ? "active" : ""}`}>
            <button className="list-name" onClick={() => show(l)}>{l.name}</button>
            <span className="list-count">{l.count}</span>
            <button className="edit" title="Delete list" onClick={(e) => remove(l, e)}>🗑</button>
          </div>
        ))}
      </div>
    </div>
  );
}
