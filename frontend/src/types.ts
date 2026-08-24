export interface Factor {
  type: string;
  detail: string;
  contribution: number;
}

export type MediaType = "movie" | "tv";

export interface GraphNode {
  id: number;
  title: string;
  year: number | null;
  x: number;
  y: number;
  cluster_id: number | null;
  rating: number | null;
  watched_date: string | null;
  poster: string | null;
  genres: string[];
  media_type: MediaType;
  watched: boolean;
  rewatches: number;
  watch_count: number;
  // react-force-graph fixed-position fields (set client-side)
  fx?: number;
  fy?: number;
}

export interface VibeResult {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  score: number;
}

export interface PersonTitle {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  cluster: string | null;
  roles: string[];
}

export interface PersonDetail {
  id: number;
  name: string;
  roles: string[];
  titles: PersonTitle[];
  phase_count: number;
}

export interface ListSummary {
  id: number;
  name: string;
  count: number;
}

export interface ListDetail {
  id: number;
  name: string;
  items: { id: number; title: string; year: number | null; poster: string | null; media_type: MediaType }[];
  film_ids: number[];
}

export interface CompareMini {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  media_type: MediaType;
  cluster: string | null;
}

export interface CompareResult {
  a: CompareMini;
  b: CompareMini;
  same_universe: boolean;
  cosine: number | null;
  shared_people: { id: number; name: string; roles: string[] }[];
  shared_keywords: string[];
  shared_genres: string[];
  shared_collection: string | null;
  edge: { weight: number; factors: Factor[] } | null;
  path: PathLink[] | null;
}

export interface Twin {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  media_type: MediaType;
  cluster: string | null;
  similarity: number;
}

export interface Recommendation {
  tmdb_id: number;
  title: string;
  year: number | null;
  poster: string | null;
  media_type: MediaType;
  score: number;
  vote_average?: number;
  reasons: { name: string; role: string }[];
}

export interface Universe {
  media_type: MediaType;
  count: number;
  watched: number;
}

export interface FlaggedMatch {
  id: number;
  title: string;
  matched_year: number | null;
  logged_year: number | null;
  poster: string | null;
  media_type: MediaType;
}

export interface SearchResult {
  tmdb_id: number;
  title: string;
  year: number | null;
  overview: string | null;
  poster: string | null;
  media_type: MediaType;
  already_added: boolean;
}

export interface GraphEdge {
  source: number | GraphNode;
  target: number | GraphNode;
  weight: number;
  factors: Factor[];
}

export interface Cluster {
  id: number;
  label: string | null;
  raw_label?: string | null;
  user_label: string | null;
  size: number;
  x: number | null;
  y: number | null;
}

export interface GraphData {
  media_type: MediaType;
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters: Cluster[];
  edge_types: string[];
  threshold: number;
}

export interface Connection {
  film: { id: number; title: string; year: number | null; poster: string | null };
  weight: number;
  factors: Factor[];
}

export interface Neighbor {
  id: number;
  title: string;
  year: number | null;
  poster: string | null;
  similarity: number;
}

export interface Theme {
  name: string;
  keyword_id: number | null;   // null = LLM theme (highlight by name), else keyword id
}

export interface FilmDetail extends GraphNode {
  overview: string | null;
  tagline: string | null;
  runtime: number | null;
  cluster: { id: number; label: string | null } | null;
  credits: Record<string, { id: number; name: string }[]>;
  connections: Connection[];
  neighbors: Neighbor[];
  themes: Theme[];
  themes_source: "llm" | "keywords";
}

export interface Analytics {
  media_type: MediaType;
  totals: { titles: number; watched: number; runtime_hours: number; runtime_days: number };
  by_decade: { decade: number; count: number }[];
  by_watch_year: { year: number; count: number }[];
  top_genres: { name: string; count: number }[];
  collaborators: Record<string, { name: string; count: number }[]>;
  phases: { label: string | null; size: number }[];
  hubs: { id: number; title: string; year: number | null; poster: string | null; score: number }[];
}

export interface PathReason {
  connected: boolean;
  chain: PathLink[];
  degrees?: number;
  reason?: string;
}

export interface PathLink {
  from: { id: number; title: string; year: number | null };
  to: { id: number; title: string; year: number | null };
  via: { person: string; role: string }[];
}

export interface PathResult {
  connected: boolean;
  chain: PathLink[];
  degrees?: number;
}

export interface AppConfig {
  default_threshold: number;
  role_weights: Record<string, number>;
  edge_types: string[];
  universes: Universe[];
  nodes: { size_by: string; color_by: string };
  embedding: { provider: string; model: string };
}
