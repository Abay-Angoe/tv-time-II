import { useEffect, useState } from "react";
import { api } from "../api";
import type { MediaType, PersonDetail } from "../types";
import { roleLabel } from "../colors";

interface Props {
  personId: number;
  mediaType: MediaType;
  onClose: () => void;
  onSelect: (id: number) => void;
  onHighlight: (hl: { label: string; ids: Set<number> } | null) => void;
}

export default function PersonModal({ personId, mediaType, onClose, onSelect, onHighlight }: Props) {
  const [data, setData] = useState<PersonDetail | null>(null);

  useEffect(() => {
    let alive = true;
    api.person(personId, mediaType).then((d) => {
      if (!alive) return;
      setData(d);
      onHighlight({ label: d.name, ids: new Set(d.titles.map((t) => t.id)) });
    }).catch(() => {});
    return () => { alive = false; };
  }, [personId, mediaType]);

  const close = () => { onHighlight(null); onClose(); };

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal person-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={close}>×</button>
        {!data ? <div className="hint">Loading…</div> : (
          <>
            <h2>{data.name}</h2>
            <div className="meta">
              {data.roles.map(roleLabel).join(" · ")} · {data.titles.length}{" "}
              {mediaType === "tv" ? "shows" : "films"} across {data.phase_count} phases
            </div>
            <div className="person-grid">
              {data.titles.map((t) => (
                <button key={t.id} className="person-title" onClick={() => { onSelect(t.id); }}>
                  {t.poster ? <img src={t.poster} alt={t.title} />
                    : <div className="noposter">{t.title}</div>}
                  <span className="pt-title">{t.title}{t.year ? ` (${t.year})` : ""}</span>
                  {t.cluster && <span className="pt-cluster">{t.cluster}</span>}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
