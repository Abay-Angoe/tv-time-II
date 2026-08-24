import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import ForceGraph2D, { ForceGraphMethods } from "react-force-graph-2d";
import type { Cluster, GraphEdge, GraphNode } from "../types";
import { clusterColor, edgeTypeColor } from "../colors";

const SCALE = 12; // projection space is 0-100; scale to a comfortable pixel canvas

export interface MapHandle {
  focusFilm: (id: number) => void;
  resetView: () => void;
}

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters: Cluster[];
  selectedId: number | null;
  dimmedIds: Set<number>; // filtered-out nodes render faint
  hiddenIds?: Set<number>; // time-lapse: not-yet-revealed nodes render (almost) invisible
  pathEdgeKeys: Set<string>;
  pathNodeIds: Set<number>;
  onSelect: (id: number) => void;
}

const edgeKey = (a: number, b: number) => (a < b ? `${a}-${b}` : `${b}-${a}`);
const idOf = (n: number | GraphNode) => (typeof n === "number" ? n : n.id);

const MapCanvas = forwardRef<MapHandle, Props>(function MapCanvas(
  { nodes, edges, clusters, selectedId, dimmedIds, hiddenIds, pathEdgeKeys, pathNodeIds, onSelect },
  ref,
) {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Fix node positions from the projection — this projection IS the layout.
  const graphData = useMemo(() => {
    const nodeObjs = nodes.map((n) => ({
      ...n,
      x: n.x * SCALE,
      y: n.y * SCALE,
      fx: n.x * SCALE,
      fy: n.y * SCALE,
    }));
    const links = edges.map((e) => ({
      source: idOf(e.source),
      target: idOf(e.target),
      weight: e.weight,
      factors: e.factors,
    }));
    return { nodes: nodeObjs, links };
  }, [nodes, edges]);

  useImperativeHandle(ref, () => ({
    focusFilm: (id: number) => {
      const n = nodes.find((x) => x.id === id);
      if (n && fgRef.current) {
        fgRef.current.centerAt(n.x * SCALE, n.y * SCALE, 800);
        fgRef.current.zoom(4, 800);
      }
    },
    resetView: () => fgRef.current?.zoomToFit(600, 60),
  }));

  useEffect(() => {
    // Kill forces so nodes stay exactly where the projection put them.
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge", null as never);
    fg.d3Force("link", null as never);
    fg.d3Force("center", null as never);
    const t = setTimeout(() => fg.zoomToFit(400, 60), 150);
    return () => clearTimeout(t);
  }, [graphData.nodes.length]);

  const nodeSize = (n: GraphNode) => {
    const base = 2.2;
    // Favorites signal: TV Time rewatches (ratings aren't in the export). More
    // rewatched -> bigger. Falls back to rating if present.
    if (n.rewatches && n.rewatches > 0) return base + Math.min(n.rewatches, 6) * 0.9;
    if (n.rating != null) return base + Math.min(n.rating, 10) * 0.32;
    return base;
  };

  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as GraphNode;
      if (hiddenIds && hiddenIds.has(n.id)) return; // time-lapse: not revealed yet
      const r = nodeSize(n);
      const dimmed = dimmedIds.has(n.id);
      const isSel = n.id === selectedId;
      const inPath = pathNodeIds.has(n.id);
      const color = clusterColor(n.cluster_id);

      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      if (n.watched) {
        // Watched: solid filled dot.
        ctx.globalAlpha = dimmed ? 0.12 : 1;
        ctx.fillStyle = color;
        ctx.fill();
      } else {
        // Followed-but-unwatched (TV): hollow ring, faint fill.
        ctx.globalAlpha = dimmed ? 0.06 : 0.22;
        ctx.fillStyle = color;
        ctx.fill();
        ctx.globalAlpha = dimmed ? 0.18 : 0.9;
        ctx.lineWidth = 1.1 / globalScale;
        ctx.strokeStyle = color;
        ctx.stroke();
      }

      if (isSel || inPath) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1.6 / globalScale;
        ctx.strokeStyle = isSel ? "#ffffff" : "#fbbf24";
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // Titles appear when zoomed in, or always for the selected/path nodes.
      if ((globalScale > 3 && !dimmed) || isSel || inPath) {
        const label = n.year ? `${n.title} (${n.year})` : n.title;
        const fontSize = Math.max(9 / globalScale, 2.4);
        ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
        ctx.fillStyle = "rgba(230,230,235,0.9)";
        ctx.textAlign = "center";
        ctx.fillText(label, node.x, node.y + r + fontSize + 1);
      }
    },
    [dimmedIds, selectedId, pathNodeIds],
  );

  const drawClusterLabels = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (globalScale > 6) return; // hide island labels once deeply zoomed in
      ctx.textAlign = "center";
      for (const c of clusters) {
        if (c.x == null || c.y == null || !c.label) continue;
        const fontSize = Math.max(13 / globalScale, 3);
        ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
        ctx.fillStyle = "rgba(255,255,255,0.55)";
        ctx.fillText(c.label.toUpperCase(), c.x * SCALE, c.y * SCALE);
      }
    },
    [clusters],
  );

  const linkColor = useCallback(
    (link: any) => {
      const key = edgeKey(idOf(link.source), idOf(link.target));
      if (pathEdgeKeys.has(key)) return "rgba(251,191,36,0.95)";
      const top = (link.factors && link.factors[0]?.type) || "keyword";
      const base = edgeTypeColor(top);
      const a = 0.12 + Math.min(link.weight, 1) * 0.5;
      return hexToRgba(base, a);
    },
    [pathEdgeKeys],
  );

  return (
    <div ref={wrapRef} style={{ position: "absolute", inset: 0 }}>
      <ForceGraph2D
        ref={fgRef as never}
        graphData={graphData}
        backgroundColor="#0b0d12"
        nodeRelSize={1}
        nodeCanvasObject={drawNode}
        nodePointerAreaPaint={(node: any, color, ctx) => {
          if (hiddenIds && hiddenIds.has((node as GraphNode).id)) return;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeSize(node as GraphNode) + 2, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkColor={linkColor}
        linkWidth={(l: any) => (pathEdgeKeys.has(edgeKey(idOf(l.source), idOf(l.target))) ? 2.5 : 0.5 + l.weight)}
        linkDirectionalParticles={0}
        cooldownTicks={0}
        warmupTicks={0}
        onNodeClick={(node: any) => onSelect((node as GraphNode).id)}
        onRenderFramePost={drawClusterLabels}
        enableNodeDrag={false}
      />
    </div>
  );
});

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export default MapCanvas;
