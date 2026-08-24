import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { AppConfig, Cluster, GraphData, GraphEdge, MediaType, PathResult } from "./types";
import MapCanvas, { MapHandle } from "./components/MapCanvas";
import Controls, { Filters } from "./components/Controls";
import InspectPanel from "./components/InspectPanel";
import Pathfinder from "./components/Pathfinder";
import ClusterList from "./components/ClusterList";
import AnalyticsView from "./components/AnalyticsView";
import AddModal from "./components/AddModal";
import VibeSearch from "./components/VibeSearch";
import RecommendationsView from "./components/RecommendationsView";
import PersonModal from "./components/PersonModal";
import FindTitle from "./components/FindTitle";
import TimeLapse from "./components/TimeLapse";
import ListsPanel from "./components/ListsPanel";
import CompareView from "./components/CompareView";
import RelinkModal from "./components/RelinkModal";
import FlaggedModal from "./components/FlaggedModal";
import type { ListSummary } from "./types";
import "./styles.css";

const idOf = (n: number | { id: number }) => (typeof n === "number" ? n : n.id);
const edgeKey = (a: number, b: number) => (a < b ? `${a}-${b}` : `${b}-${a}`);
const EMPTY_FILTERS: Filters = { decade: null, minRating: 0, clusterId: null, watched: "all" };

export default function App() {
  const [mediaType, setMediaType] = useState<MediaType>("movie");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [threshold, setThreshold] = useState(0.35);
  const [showEdges, setShowEdges] = useState(true);
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pathFromId, setPathFromId] = useState<number | null>(null);
  const [pathResult, setPathResult] = useState<PathResult | null>(null);
  const [visited, setVisited] = useState<number[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [showRecs, setShowRecs] = useState(false);
  const [personId, setPersonId] = useState<number | null>(null);
  // Unified map highlight used by themes, vibe search, and person spotlight.
  const [highlight, setHighlight] = useState<{ label: string; ids: Set<number> } | null>(null);
  const [tl, setTl] = useState<{ on: boolean; playing: boolean; cursor: number }>({ on: false, playing: false, cursor: 0 });
  const [lists, setLists] = useState<ListSummary[]>([]);
  const [activeListId, setActiveListId] = useState<number | null>(null);
  const [compare, setCompare] = useState<{ open: boolean; a: number | null }>({ open: false, a: null });
  const [relink, setRelink] = useState<{ id: number; title: string } | null>(null);
  const [showFlagged, setShowFlagged] = useState(false);

  const reloadLists = () => { api.lists().then(setLists).catch(() => {}); };
  useEffect(() => { reloadLists(); }, []);
  // Highlight helpers keep the active-list indicator in sync across highlight sources.
  const applyHighlight = (hl: { label: string; ids: Set<number> } | null) => {
    setHighlight(hl); setActiveListId(null);
  };
  const listHighlight = (hl: { label: string; ids: Set<number> } | null, id: number | null) => {
    setHighlight(hl); setActiveListId(id);
  };

  const mapRef = useRef<MapHandle>(null);

  async function loadUniverse(mt: MediaType) {
    setLoading(true);
    try {
      const [cfg, g] = await Promise.all([api.config(mt), api.graph(mt)]);
      setConfig(cfg);
      setGraph(g);
      setThreshold(cfg.default_threshold);
      setEnabledTypes(new Set(g.edge_types));
      setFilters(EMPTY_FILTERS);
      setSelectedId(null);
      setPathFromId(null);
      setPathResult(null);
      setVisited([]);
      setHighlight(null);
      setActiveListId(null);
      setShowAnalytics(false);
      setShowAdd(false);
      setShowRecs(false);
      setPersonId(null);
      setCompare({ open: false, a: null });
      setRelink(null);
      setShowFlagged(false);
      setTl({ on: false, playing: false, cursor: 0 });
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadUniverse("movie"); }, []);

  const switchUniverse = (mt: MediaType) => {
    if (mt === mediaType) return;
    setMediaType(mt);
    loadUniverse(mt);
  };

  const decades = useMemo(() => {
    if (!graph) return [];
    const set = new Set<number>();
    for (const n of graph.nodes) if (n.year) set.add(Math.floor(n.year / 10) * 10);
    return [...set].sort((a, b) => a - b);
  }, [graph]);

  const filtersActive =
    filters.decade != null || filters.minRating > 0 || filters.clusterId != null ||
    filters.watched !== "all";

  const passes = useMemo(() => {
    const byId = new Map(graph?.nodes.map((n) => [n.id, n]) ?? []);
    return (nodeId: number) => {
      const n = byId.get(nodeId);
      if (!n) return false;
      if (filters.decade != null && (!n.year || Math.floor(n.year / 10) * 10 !== filters.decade)) return false;
      if (filters.minRating > 0 && (n.rating == null || n.rating < filters.minRating)) return false;
      if (filters.clusterId != null && n.cluster_id !== filters.clusterId) return false;
      if (filters.watched === "watched" && !n.watched) return false;
      if (filters.watched === "unwatched" && n.watched) return false;
      return true;
    };
  }, [graph, filters]);

  const dimmedIds = useMemo(() => {
    const s = new Set<number>();
    if (!graph || (!filtersActive && !highlight)) return s;
    for (const n of graph.nodes) {
      if (filtersActive && !passes(n.id)) { s.add(n.id); continue; }
      if (highlight && !highlight.ids.has(n.id)) s.add(n.id);
    }
    return s;
  }, [graph, filtersActive, passes, highlight]);

  // --- time-lapse ---
  const watchTs = useMemo(() => {
    if (!graph) return { min: 0, max: 0, count: 0 };
    const ts = graph.nodes
      .map((n) => (n.watched_date ? Date.parse(n.watched_date) : NaN))
      .filter((t) => !isNaN(t))
      .sort((a, b) => a - b);
    return { min: ts[0] ?? 0, max: ts[ts.length - 1] ?? 0, count: ts.length };
  }, [graph]);

  const tlHidden = useMemo(() => {
    const s = new Set<number>();
    if (!graph || !tl.on) return s;
    for (const n of graph.nodes) {
      const t = n.watched_date ? Date.parse(n.watched_date) : NaN;
      if (isNaN(t) || t > tl.cursor) s.add(n.id);
    }
    return s;
  }, [graph, tl]);

  const tlRevealed = graph ? graph.nodes.length - tlHidden.size : 0;

  useEffect(() => {
    if (!tl.on || !tl.playing) return;
    const DURATION = 18000;
    const startWall = performance.now();
    const startCursor = tl.cursor >= watchTs.max ? watchTs.min : tl.cursor;
    let raf = 0;
    const step = (now: number) => {
      const frac = Math.min(1, (now - startWall) / DURATION);
      const cursor = startCursor + (watchTs.max - startCursor) * frac;
      setTl((t) => ({ ...t, cursor, playing: frac < 1 }));
      if (frac < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tl.on, tl.playing]);

  const filteredEdges: GraphEdge[] = useMemo(() => {
    if (!graph || !showEdges || tl.on) return []; // hide edges during time-lapse
    return graph.edges.filter((e) => {
      if (e.weight < threshold) return false;
      const a = idOf(e.source), b = idOf(e.target);
      if (dimmedIds.has(a) || dimmedIds.has(b)) return false;
      if (enabledTypes.size > 0) return e.factors.some((f) => enabledTypes.has(f.type));
      return false;
    });
  }, [graph, showEdges, threshold, enabledTypes, dimmedIds, tl.on]);

  const { pathEdgeKeys, pathNodeIds } = useMemo(() => {
    const keys = new Set<string>();
    const nodesSet = new Set<number>();
    if (pathResult?.connected) {
      for (const link of pathResult.chain) {
        keys.add(edgeKey(link.from.id, link.to.id));
        nodesSet.add(link.from.id);
        nodesSet.add(link.to.id);
      }
    }
    return { pathEdgeKeys: keys, pathNodeIds: nodesSet };
  }, [pathResult]);

  const select = (id: number) => {
    setSelectedId(id);
    setVisited((v) => (v.includes(id) ? v : [...v, id]));
  };

  const surprise = async () => {
    try {
      const r = await api.surprise(selectedId, visited, mediaType);
      select(r.film_id);
      mapRef.current?.focusFilm(r.film_id);
      setToast(r.reason);
      setTimeout(() => setToast(null), 3500);
    } catch { /* ignore */ }
  };

  const toggleType = (t: string) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  const onClusterRenamed = (id: number, label: string | null, userLabel: string | null) => {
    setGraph((g) => g && {
      ...g,
      clusters: g.clusters.map((c) => (c.id === id ? { ...c, label, user_label: userLabel } : c)),
    });
  };

  const focusCluster = (clusterId: number) => {
    const n = graph?.nodes.find((x) => x.cluster_id === clusterId);
    if (n) mapRef.current?.focusFilm(n.id);
  };

  const onAdded = async (filmId: number) => {
    setShowAdd(false);
    try {
      const g = await api.graph(mediaType);
      setGraph(g);
      setEnabledTypes((prev) => new Set([...prev, ...g.edge_types]));
      select(filmId);
      setTimeout(() => mapRef.current?.focusFilm(filmId), 250);
      setToast("Added to your map");
      setTimeout(() => setToast(null), 3000);
    } catch { /* ignore */ }
  };

  const highlightTheme = async (theme: { name: string; keyword_id: number | null }) => {
    try {
      const { film_ids } = theme.keyword_id != null
        ? await api.theme(theme.keyword_id, mediaType)
        : await api.themeByName(theme.name, mediaType);
      applyHighlight({ label: theme.name, ids: new Set(film_ids) });
    } catch { /* ignore */ }
  };

  const nodeIds = useMemo(() => new Set((graph?.nodes ?? []).map((n) => n.id)), [graph]);

  const pickAndFocus = (id: number) => {
    select(id);
    mapRef.current?.focusFilm(id);
  };

  const crossSelect = async (mt: MediaType, id: number) => {
    if (mt === mediaType) { pickAndFocus(id); return; }
    setMediaType(mt);
    await loadUniverse(mt);
    setSelectedId(id);
    setVisited((v) => (v.includes(id) ? v : [...v, id]));
    setTimeout(() => mapRef.current?.focusFilm(id), 350);
  };

  const onFilmUpdated = (id: number, patch: { watched: boolean; rewatches: number }) => {
    setGraph((g) => g && {
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
    });
  };

  const reloadGraph = async (selectId?: number | null) => {
    try {
      const g = await api.graph(mediaType);
      setGraph(g);
      setEnabledTypes((prev) => new Set([...prev, ...g.edge_types]));
      if (selectId != null) { select(selectId); setTimeout(() => mapRef.current?.focusFilm(selectId), 250); }
    } catch { /* ignore */ }
  };

  const onRelinkDone = (newFilmId: number) => {
    setRelink(null);
    reloadGraph(newFilmId);
    setToast("Re-linked to the correct match");
    setTimeout(() => setToast(null), 3000);
  };

  const onRemoved = (id: number) => {
    if (selectedId === id) setSelectedId(null);
    reloadGraph(null);
    setToast("Removed from your collection");
    setTimeout(() => setToast(null), 3000);
  };

  if (error) return <div className="fatal">Backend error: {error}<br />Is the API running on :8000 and the pipeline run?</div>;
  if (loading || !config || !graph) return <div className="loading">Mapping your {mediaType === "tv" ? "TV" : "cinema"} universe…</div>;

  const clustersForFilter: Cluster[] = graph.clusters.filter((c) => c.id >= 0);
  const universes = config.universes;
  const phases = graph.clusters.filter((c) => c.id >= 0).length;

  return (
    <div className="app">
      <MapCanvas
        ref={mapRef}
        nodes={graph.nodes}
        edges={filteredEdges}
        clusters={graph.clusters}
        selectedId={selectedId}
        dimmedIds={dimmedIds}
        hiddenIds={tl.on ? tlHidden : undefined}
        pathEdgeKeys={pathEdgeKeys}
        pathNodeIds={pathNodeIds}
        onSelect={select}
      />

      <header className="topbar">
        <div className="brand">◎ {mediaType === "tv" ? "TV Universe" : "Cinema Universe"}</div>
        <div className="universe-toggle">
          {universes.map((u) => (
            <button
              key={u.media_type}
              className={`uni-btn ${u.media_type === mediaType ? "on" : ""}`}
              onClick={() => switchUniverse(u.media_type)}
            >
              {u.media_type === "tv" ? "📺 TV" : "🎬 Movies"} <span className="uni-count">{u.count}</span>
            </button>
          ))}
        </div>
        <div className="counts">
          {graph.nodes.length} {mediaType === "tv" ? "shows" : "films"} · {phases} phases · {filteredEdges.length} connections
        </div>
        <button className="btn ghost" onClick={() => setShowRecs(true)}>🎯 Recommend</button>
        <button className="btn ghost" onClick={() => setShowAdd(true)}>＋ Add</button>
        <button className="btn ghost" onClick={() => setShowAnalytics(true)}>✨ Wrapped</button>
        {watchTs.count > 1 && (
          <button className="btn ghost" onClick={() => setTl({ on: true, playing: true, cursor: watchTs.min })}>⏳ Time-lapse</button>
        )}
        <button className="btn ghost" onClick={() => setCompare({ open: true, a: selectedId })}>⇄ Compare</button>
        <button className="btn ghost" onClick={() => setShowFlagged(true)}>⚑ Review</button>
        <button className="btn ghost" onClick={() => window.open(api.snapshotUrl(mediaType), "_blank")}>⬇ Export</button>
        <button className="btn ghost" onClick={() => mapRef.current?.resetView()}>Reset view</button>
      </header>

      {highlight && (
        <div className="theme-banner">
          <b>{highlight.label}</b> · {highlight.ids.size} {mediaType === "tv" ? "shows" : "films"}
          <button className="theme-clear" onClick={() => { setHighlight(null); setActiveListId(null); }}>clear ×</button>
        </div>
      )}

      <aside className="left">
        <FindTitle nodes={graph.nodes} onPick={pickAndFocus} />
        <VibeSearch mediaType={mediaType} onHighlight={applyHighlight} onPick={pickAndFocus} />
        <Controls
          config={config}
          mediaType={mediaType}
          threshold={threshold}
          onThreshold={setThreshold}
          edgeTypes={graph.edge_types}
          enabledTypes={enabledTypes}
          onToggleType={toggleType}
          showEdges={showEdges}
          onToggleEdges={setShowEdges}
          filters={filters}
          onFilters={setFilters}
          decades={decades}
          clusters={clustersForFilter}
          edgeCount={filteredEdges.length}
          onSurprise={surprise}
        />
        {mediaType === "tv" && (
          <div className="panel legend">
            <span><span className="lg-dot solid" /> watched</span>
            <span><span className="lg-dot hollow" /> followed · unwatched</span>
          </div>
        )}
        <Pathfinder
          nodes={graph.nodes}
          fromId={pathFromId}
          onFrom={setPathFromId}
          onResult={setPathResult}
          onSelect={select}
        />
        <ListsPanel
          lists={lists}
          nodeIds={nodeIds}
          activeListId={activeListId}
          onReload={reloadLists}
          onHighlight={listHighlight}
        />
        <ClusterList clusters={graph.clusters} onRenamed={onClusterRenamed} onFocus={focusCluster} />
      </aside>

      {selectedId != null && (
        <aside className="right">
          <InspectPanel
            filmId={selectedId}
            onSelect={select}
            onPathFrom={(id) => setPathFromId(id)}
            onThemeClick={highlightTheme}
            onPersonClick={(id) => setPersonId(id)}
            onFilmUpdated={onFilmUpdated}
            onCrossSelect={crossSelect}
            onCompare={(id) => setCompare({ open: true, a: id })}
            onRelink={(id, title) => setRelink({ id, title })}
            onRemoved={onRemoved}
            lists={lists}
            onListsChanged={reloadLists}
            onClose={() => setSelectedId(null)}
          />
        </aside>
      )}

      {showAnalytics && (
        <AnalyticsView mediaType={mediaType} onClose={() => setShowAnalytics(false)} onSelect={select} />
      )}

      {showAdd && (
        <AddModal mediaType={mediaType} onClose={() => setShowAdd(false)} onAdded={onAdded} />
      )}

      {showRecs && (
        <RecommendationsView
          mediaType={mediaType}
          clusters={graph.clusters}
          onClose={() => setShowRecs(false)}
          onAdded={onAdded}
        />
      )}

      {personId != null && (
        <PersonModal
          personId={personId}
          mediaType={mediaType}
          onClose={() => setPersonId(null)}
          onSelect={pickAndFocus}
          onHighlight={applyHighlight}
        />
      )}

      {compare.open && (
        <CompareView
          nodes={graph.nodes}
          initialA={compare.a}
          onClose={() => setCompare({ open: false, a: null })}
          onSelect={(id) => { setCompare({ open: false, a: null }); pickAndFocus(id); }}
        />
      )}

      {showFlagged && (
        <FlaggedModal
          mediaType={mediaType}
          onClose={() => setShowFlagged(false)}
          onRelink={(id, title) => { setShowFlagged(false); setRelink({ id, title }); }}
          onRemoved={() => reloadGraph(null)}
        />
      )}

      {relink && (
        <RelinkModal
          filmId={relink.id}
          mediaType={mediaType}
          initialQuery={relink.title}
          onDone={onRelinkDone}
          onClose={() => setRelink(null)}
        />
      )}

      {tl.on && (
        <TimeLapse
          minTs={watchTs.min}
          maxTs={watchTs.max}
          cursor={tl.cursor}
          playing={tl.playing}
          revealed={tlRevealed}
          total={graph.nodes.length}
          noun={mediaType === "tv" ? "shows" : "films"}
          onToggle={() => setTl((t) => ({ ...t, playing: !t.playing, cursor: t.cursor >= watchTs.max ? watchTs.min : t.cursor }))}
          onScrub={(ts) => setTl((t) => ({ ...t, cursor: ts, playing: false }))}
          onClose={() => setTl({ on: false, playing: false, cursor: 0 })}
        />
      )}

      {toast && <div className="toast">✨ {toast}</div>}
    </div>
  );
}
