import { useState } from "react";
import { api } from "../api";
import type { Cluster } from "../types";
import { clusterColor } from "../colors";

interface Props {
  clusters: Cluster[];
  onRenamed: (id: number, label: string | null, userLabel: string | null) => void;
  onFocus: (clusterId: number) => void;
}

export default function ClusterList({ clusters, onRenamed, onFocus }: Props) {
  return (
    <div className="panel clusters">
      <h3>Your phases</h3>
      <div className="cluster-items">
        {clusters
          .filter((c) => c.id >= 0)
          .sort((a, b) => b.size - a.size)
          .map((c) => (
            <ClusterRow key={c.id} cluster={c} onRenamed={onRenamed} onFocus={onFocus} />
          ))}
      </div>
    </div>
  );
}

function ClusterRow({ cluster, onRenamed, onFocus }: {
  cluster: Cluster;
  onRenamed: (id: number, label: string | null, userLabel: string | null) => void;
  onFocus: (clusterId: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(cluster.label ?? "");

  const save = async () => {
    const val = draft.trim();
    const res = await api.renameCluster(cluster.id, val || null);
    onRenamed(cluster.id, res.label, res.user_label);
    setEditing(false);
  };

  return (
    <div className="cluster-row">
      <span className="swatch" style={{ background: clusterColor(cluster.id) }} />
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
          onBlur={save}
        />
      ) : (
        <>
          <button className="cluster-name" onClick={() => onFocus(cluster.id)} title="Focus on map">
            {cluster.label ?? `Cluster ${cluster.id}`}
          </button>
          <span className="cluster-size">{cluster.size}</span>
          <button className="edit" title="Rename" onClick={() => { setDraft(cluster.label ?? ""); setEditing(true); }}>✎</button>
        </>
      )}
    </div>
  );
}
