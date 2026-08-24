import type {
  Analytics, AppConfig, CompareResult, FilmDetail, FlaggedMatch, GraphData, ListDetail,
  ListSummary, MediaType, PathResult, PersonDetail, Recommendation, SearchResult, Twin,
  VibeResult,
} from "./types";

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${url} -> ${res.status}`);
  return res.json();
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.json();
}

export const api = {
  config: (mt: MediaType = "movie") => get<AppConfig>(`/api/config?media_type=${mt}`),
  stats: () => get<{ by_type: Record<string, { films: number; watched: number; embedded: number }>; clusters: number; edges: number }>("/api/stats"),
  // Fetch ALL stored edges (threshold 0) once per universe; slider filters client-side.
  graph: (mt: MediaType) => get<GraphData>(`/api/graph?media_type=${mt}&threshold=0`),
  film: (id: number) => get<FilmDetail>(`/api/film/${id}`),
  path: (from: number, to: number) => get<PathResult>(`/api/path?from=${from}&to=${to}`),
  surprise: (from: number | null, visited: number[], mt: MediaType) => {
    const params = new URLSearchParams({ media_type: mt });
    if (from != null) params.set("from", String(from));
    if (visited.length) params.set("visited", visited.join(","));
    return get<{ film_id: number; reason: string }>(`/api/surprise?${params.toString()}`);
  },
  analytics: (mt: MediaType) => get<Analytics>(`/api/analytics?media_type=${mt}`),
  vibe: (q: string, mt: MediaType) =>
    get<{ results: VibeResult[] }>(`/api/vibe?q=${encodeURIComponent(q)}&media_type=${mt}`),
  person: (personId: number, mt: MediaType) =>
    get<PersonDetail>(`/api/person/${personId}?media_type=${mt}`),
  twins: (filmId: number) =>
    get<{ media_type: MediaType; twins: Twin[] }>(`/api/twin/${filmId}`),
  compare: (a: number, b: number) => get<CompareResult>(`/api/compare?a=${a}&b=${b}`),
  snapshotUrl: (mt: MediaType) => `/api/snapshot?media_type=${mt}`,
  // lists
  lists: () => get<ListSummary[]>("/api/lists"),
  listDetail: (id: number) => get<ListDetail>(`/api/lists/${id}`),
  createList: (name: string) => send<ListSummary>("/api/lists", "POST", { name }),
  deleteList: (id: number) => send<{ ok: boolean }>(`/api/lists/${id}`, "DELETE"),
  addToList: (listId: number, filmId: number) =>
    send<{ ok: boolean }>(`/api/lists/${listId}/items`, "POST", { film_id: filmId }),
  removeFromList: (listId: number, filmId: number) =>
    send<{ ok: boolean }>(`/api/lists/${listId}/items/${filmId}`, "DELETE"),
  filmLists: (filmId: number) => get<{ list_ids: number[] }>(`/api/film/${filmId}/lists`),
  flagged: (mt: MediaType) => get<{ flagged: FlaggedMatch[] }>(`/api/flagged?media_type=${mt}`),
  relink: (filmId: number, tmdbId: number) =>
    send<{ film_id: number; title: string; media_type: MediaType }>(
      `/api/film/${filmId}/relink`, "POST", { tmdb_id: tmdbId }),
  removeFilm: (filmId: number) =>
    send<{ removed: number; title: string }>(`/api/film/${filmId}`, "DELETE"),
  recommend: (mt: MediaType, clusterId: number | null, mode: "taste" | "blindspots" = "taste") =>
    get<{ recommendations: Recommendation[]; based_on: { name: string; role: string; count: number }[] }>(
      `/api/recommend?media_type=${mt}&mode=${mode}${clusterId != null ? `&cluster_id=${clusterId}` : ""}`),
  search: (q: string, mt: MediaType) =>
    get<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(q)}&media_type=${mt}`),
  add: async (tmdbId: number, mt: MediaType, watched: boolean) => {
    const res = await fetch("/api/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tmdb_id: tmdbId, media_type: mt, watched }),
    });
    if (!res.ok) throw new Error(`add failed: ${res.status}`);
    return res.json() as Promise<{ film_id: number; title: string; media_type: MediaType }>;
  },
  theme: (keywordId: number, mt: MediaType) =>
    get<{ film_ids: number[] }>(`/api/theme?keyword_id=${keywordId}&media_type=${mt}`),
  themeByName: (name: string, mt: MediaType) =>
    get<{ film_ids: number[] }>(`/api/theme_by_name?name=${encodeURIComponent(name)}&media_type=${mt}`),
  setWatched: async (id: number, watched: boolean) => {
    const res = await fetch(`/api/film/${id}/watched`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watched }),
    });
    if (!res.ok) throw new Error(`setWatched failed: ${res.status}`);
    return res.json() as Promise<{ id: number; watched: boolean; rewatches: number }>;
  },
  logRewatch: async (id: number) => {
    const res = await fetch(`/api/film/${id}/rewatch`, { method: "POST" });
    if (!res.ok) throw new Error(`rewatch failed: ${res.status}`);
    return res.json() as Promise<{ id: number; watched: boolean; rewatches: number }>;
  },
  renameCluster: async (id: number, userLabel: string | null) => {
    const res = await fetch(`/api/clusters/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_label: userLabel }),
    });
    if (!res.ok) throw new Error(`rename failed: ${res.status}`);
    return res.json() as Promise<{ id: number; label: string | null; user_label: string | null }>;
  },
};
