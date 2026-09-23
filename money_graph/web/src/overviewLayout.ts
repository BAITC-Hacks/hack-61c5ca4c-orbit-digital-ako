import type { GraphData } from "./types";

// A bounded grid keeps disconnected communities from compressing the connected
// core. Traverse neighbours together so nearby cells tend to share links.
export function overviewPositions(
  data: GraphData,
  width: number,
  height: number,
) {
  const neighbours = new Map(data.nodes.map((n) => [n.gid, new Set<string>()]));
  for (const edge of data.edges) {
    neighbours.get(edge.src)?.add(edge.dst);
    neighbours.get(edge.dst)?.add(edge.src);
  }
  const ordered = [...neighbours.keys()].sort(
    (a, b) =>
      neighbours.get(b)!.size - neighbours.get(a)!.size ||
      a.localeCompare(b, undefined, { numeric: true }),
  );
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const first of ordered) {
    if (seen.has(first)) continue;
    const queue = [first];
    seen.add(first);
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      ids.push(id);
      for (const next of neighbours.get(id) || []) {
        if (neighbours.has(next) && !seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }
  const aspect = Math.max(0.65, Math.min(1.7, width / Math.max(1, height)));
  const columns = Math.max(1, Math.ceil(Math.sqrt(ids.length * aspect)));
  const positions: Record<string, { x: number; y: number }> = {};
  ids.forEach((id, i) => {
    const row = Math.floor(i / columns);
    const col = i % columns;
    positions[id] = {
      x: (row % 2 ? columns - 1 - col : col) * 100,
      y: -row * 100,
    };
  });
  return positions;
}
