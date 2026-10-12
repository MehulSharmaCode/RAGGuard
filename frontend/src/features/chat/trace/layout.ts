/**
 * Geometry for the Evidence Trace, in abstract world units shared by the 3D
 * scene and the 2D SVG fallback. Four stations left to right:
 *   Documents (page tiles) → Chunks (strips in document order) → Evidence (one node
 *   per returned source) → Answer.
 *
 * Positions encode only real facts: page number, chunk order (chunk_index) within a
 * document, rank in the response, and the cited flag. When a document has more
 * pages or chunks than fit, tiles/strips are scaled (each stands for a range) and
 * the layout reports that, so the UI can say so. No embedding coordinates exist in
 * the API, so none are drawn.
 */

export interface SceneRetrieval {
  key: string;
  page: number | null;
  chunkIndex: number;
}

export interface SceneDocumentInput {
  /** Known total pages (PDF); null for TXT or when unknown. */
  totalPages: number | null;
  /** Known total chunks; null when unknown (document no longer listed). */
  chunkCount: number | null;
  retrieved: SceneRetrieval[];
}

export interface SceneEvidenceInput {
  key: string;
  documentIndex: number;
  cited: boolean;
  /** Link strength in 0..1; for real traces this is the similarity score. */
  strength: number;
}

export interface SceneInput {
  documents: SceneDocumentInput[];
  evidence: SceneEvidenceInput[];
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PageTile extends Box {
  documentIndex: number;
  keys: string[];
}

export interface Strip extends Box {
  documentIndex: number;
  keys: string[];
}

export interface EvidenceNode extends Box {
  key: string;
  cited: boolean;
}

export type LinkKind = "page-chunk" | "chunk-evidence" | "evidence-answer";

export interface Link {
  kind: LinkKind;
  key: string;
  from: [number, number];
  to: [number, number];
  strength: number;
  /** Station the link leads into (1 chunks, 2 evidence, 3 answer). */
  station: 1 | 2 | 3;
}

export interface DocumentScale {
  pagesScaled: boolean;
  chunksScaled: boolean;
  tiles: number;
  strips: number;
}

export interface SceneLayout {
  pages: PageTile[];
  strips: Strip[];
  nodes: EvidenceNode[];
  answer: Box;
  links: Link[];
  scale: DocumentScale[];
}

export const STATION_X = [-6, -2, 2, 6] as const;
export const VIEW = { width: 16.4, height: 8.2 } as const;
const HEIGHT = 7.2;
const PAGE_COLUMNS = 4;
const STRIP_WIDTH = 1.2;
const ANSWER: Box = { x: STATION_X[3], y: 0, w: 1.6, h: 3.0 };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Map a 0-based position among `total` items onto `slots` scaled slots. */
function scaled(position: number, total: number, slots: number): number {
  if (total <= slots) return clamp(position, 0, slots - 1);
  return clamp(Math.floor((position * slots) / total), 0, slots - 1);
}

export function computeLayout(input: SceneInput): SceneLayout {
  const docCount = Math.max(1, input.documents.length);
  const band = HEIGHT / docCount;
  const pages: PageTile[] = [];
  const strips: Strip[] = [];
  const scale: DocumentScale[] = [];
  const tileOf = new Map<string, PageTile>();
  const stripOf = new Map<string, Strip>();

  input.documents.forEach((doc, d) => {
    const centerY = HEIGHT / 2 - band * (d + 0.5);

    // --- page tiles: real page count for PDFs; otherwise one tile per distinct retrieved page.
    const distinctPages = [...new Set(doc.retrieved.map((r) => r.page))];
    const pagesKnown = doc.totalPages !== null && doc.totalPages > 0;
    const needed = pagesKnown ? doc.totalPages! : Math.max(1, distinctPages.length);
    const maxRows = Math.max(1, Math.floor((band * 0.85) / 0.52));
    const tileCount = Math.min(needed, PAGE_COLUMNS * maxRows);
    const rows = Math.ceil(tileCount / PAGE_COLUMNS);
    // Few pages are drawn large; many pages shrink to fit the band.
    const tileH = clamp((band * 0.8) / rows - 0.1, 0.12, 0.9);
    const tileW = tileH * 0.77;
    const cols = Math.min(PAGE_COLUMNS, tileCount);
    const docTiles: PageTile[] = [];
    for (let t = 0; t < tileCount; t++) {
      const col = t % PAGE_COLUMNS;
      const row = Math.floor(t / PAGE_COLUMNS);
      const tile: PageTile = {
        documentIndex: d,
        keys: [],
        x: STATION_X[0] + (col - (cols - 1) / 2) * (tileW + 0.1),
        y: centerY + ((rows - 1) / 2 - row) * (tileH + 0.1),
        w: tileW,
        h: tileH,
      };
      docTiles.push(tile);
      pages.push(tile);
    }
    for (const r of doc.retrieved) {
      const position = pagesKnown && r.page !== null ? r.page - 1 : distinctPages.indexOf(r.page);
      const tile = docTiles[scaled(position, needed, tileCount)]!;
      tile.keys.push(r.key);
      tileOf.set(r.key, tile);
    }

    // --- chunk strips: real chunk order; all chunks when the count is known.
    const ordered = [...doc.retrieved].sort((a, b) => a.chunkIndex - b.chunkIndex);
    const chunkTotal = doc.chunkCount ?? ordered.length;
    const maxStrips = clamp(Math.floor((band * 0.9) / 0.12), 1, 30);
    const stripCount = Math.max(1, Math.min(chunkTotal, maxStrips));
    const pitch = Math.min(0.34, (band * 0.9) / stripCount);
    const docStrips: Strip[] = [];
    for (let s = 0; s < stripCount; s++) {
      const strip: Strip = {
        documentIndex: d,
        keys: [],
        x: STATION_X[1],
        y: centerY + ((stripCount - 1) / 2 - s) * pitch,
        w: STRIP_WIDTH,
        h: Math.max(0.03, pitch * 0.55),
      };
      docStrips.push(strip);
      strips.push(strip);
    }
    ordered.forEach((r, order) => {
      const position = doc.chunkCount !== null ? r.chunkIndex : order;
      const strip = docStrips[scaled(position, chunkTotal, stripCount)]!;
      strip.keys.push(r.key);
      stripOf.set(r.key, strip);
    });

    scale.push({
      pagesScaled: needed > tileCount,
      chunksScaled: chunkTotal > stripCount,
      tiles: tileCount,
      strips: stripCount,
    });
  });

  // --- evidence nodes, in response (rank) order.
  const m = Math.max(1, input.evidence.length);
  const nodePitch = Math.min(1.1, HEIGHT / m);
  const size = Math.min(0.5, nodePitch * 0.6);
  const nodes: EvidenceNode[] = input.evidence.map((e, i) => ({
    key: e.key,
    cited: e.cited,
    x: STATION_X[2],
    y: ((m - 1) / 2 - i) * nodePitch,
    w: size,
    h: size,
  }));

  const links: Link[] = [];
  input.evidence.forEach((e, i) => {
    const node = nodes[i]!;
    const strip = stripOf.get(e.key);
    const tile = tileOf.get(e.key);
    if (tile && strip) {
      links.push({
        kind: "page-chunk",
        key: e.key,
        from: [tile.x + tile.w / 2, tile.y],
        to: [strip.x - strip.w / 2, strip.y],
        strength: 0.5,
        station: 1,
      });
    }
    if (strip) {
      links.push({
        kind: "chunk-evidence",
        key: e.key,
        from: [strip.x + strip.w / 2, strip.y],
        to: [node.x - node.w / 2, node.y],
        strength: clamp(e.strength, 0.15, 1),
        station: 2,
      });
    }
    // Only a cited source is linked to the answer: that relationship is in the response.
    if (e.cited) {
      links.push({
        kind: "evidence-answer",
        key: e.key,
        from: [node.x + node.w / 2, node.y],
        to: [ANSWER.x - ANSWER.w / 2, clamp(node.y, -ANSWER.h / 2 + 0.15, ANSWER.h / 2 - 0.15)],
        strength: 1,
        station: 3,
      });
    }
  });

  return { pages, strips, nodes, answer: ANSWER, links, scale };
}
