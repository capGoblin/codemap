import type { Anchor, Node } from "../src/api/types";

const anchor: Anchor = { file: "a.py", start_line: 1, end_line: 2, symbol: "f", content_hash: "" };

export function node(id: string, level: number, parent: string | null, order: number): Node {
  return {
    id, level, parent_id: parent, order, title: id, does: "", input: "", output: "",
    boundary_reason: "", anchors: [anchor], effects: [], parallel_group: null,
    stale: false, warnings: [],
  };
}
