// Okabe-Ito qualitative palette — colorblind-safe, extended with tints for more
// clusters. Used to color cluster "islands" distinctly on a dark canvas.
const OKABE_ITO = [
  "#56B4E9", // sky blue
  "#E69F00", // orange
  "#009E73", // bluish green
  "#F0E442", // yellow
  "#0072B2", // blue
  "#D55E00", // vermillion
  "#CC79A7", // reddish purple
  "#94D4C0", // teal tint
  "#B7A0D0", // lavender
  "#E4A0A0", // rose
  "#8FB339", // olive
  "#7FBEEB", // pale blue
];

export function clusterColor(clusterId: number | null): string {
  if (clusterId == null) return "#6b7280"; // unclustered / noise -> grey
  return OKABE_ITO[clusterId % OKABE_ITO.length];
}

// Edge-type colors for the overlay legend + link tints.
export const EDGE_TYPE_COLORS: Record<string, string> = {
  director: "#E69F00",
  composer: "#CC79A7",
  dp: "#56B4E9",
  writer: "#009E73",
  editor: "#0072B2",
  collection: "#D55E00",
  keyword: "#94D4C0",
  actor: "#B7A0D0",
  genre: "#6b7280",
};

export function edgeTypeColor(type: string): string {
  return EDGE_TYPE_COLORS[type] ?? "#9ca3af";
}

export const ROLE_LABELS: Record<string, string> = {
  director: "Director",
  composer: "Composer",
  dp: "Cinematographer",
  writer: "Writer",
  editor: "Editor",
  actor: "Cast",
  collection: "Franchise",
  keyword: "Keyword",
  genre: "Genre",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
