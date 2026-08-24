interface Props {
  minTs: number;
  maxTs: number;
  cursor: number;
  playing: boolean;
  revealed: number;
  total: number;
  noun: string;
  onToggle: () => void;
  onScrub: (ts: number) => void;
  onClose: () => void;
}

function fmt(ts: number): string {
  try {
    return new Date(ts).toLocaleDateString("en", { year: "numeric", month: "short" });
  } catch { return ""; }
}

export default function TimeLapse(p: Props) {
  return (
    <div className="timelapse-bar">
      <button className="tl-play" onClick={p.onToggle}>{p.playing ? "⏸" : "▶"}</button>
      <div className="tl-date">{fmt(p.cursor)}</div>
      <input
        className="tl-scrub"
        type="range"
        min={p.minTs}
        max={p.maxTs}
        value={p.cursor}
        step={Math.max(1, Math.round((p.maxTs - p.minTs) / 500))}
        onChange={(e) => p.onScrub(+e.target.value)}
      />
      <div className="tl-count">{p.revealed} / {p.total} {p.noun}</div>
      <button className="tl-close" onClick={p.onClose}>✕</button>
    </div>
  );
}
