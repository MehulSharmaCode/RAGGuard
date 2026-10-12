/**
 * Evidence Trace data model, derived only from real API data:
 *  - the QueryResponse (sources: document, page, chunk index, score, cited; evidence summary)
 *  - the GET /documents listing (total pages and chunk count per document), when the
 *    document is still listed.
 * Nothing here is estimated or invented. Fields the API does not provide stay null.
 */

import type { DocumentInfo, QueryResponse } from "../../../types/api";

export interface TraceRetrieval {
  sourceId: string;
  pageNumber: number | null;
  chunkIndex: number;
}

export interface TraceDocument {
  documentId: string;
  filename: string;
  /** From GET /documents; null when the document is no longer listed. */
  fileType: string | null;
  totalPages: number | null;
  chunkCount: number | null;
  listed: boolean;
  retrieved: TraceRetrieval[];
}

export interface TraceEvidence {
  sourceId: string;
  documentId: string;
  documentIndex: number;
  filename: string;
  pageNumber: number | null;
  chunkIndex: number;
  score: number;
  cited: boolean;
  rank: number;
}

export interface TraceModel {
  documents: TraceDocument[];
  evidence: TraceEvidence[];
  citedCount: number;
  response: QueryResponse;
}

export function buildTraceModel(response: QueryResponse, listing: DocumentInfo[] | null): TraceModel {
  const byId = new Map((listing ?? []).map((d) => [d.document_id, d]));
  const documents: TraceDocument[] = [];
  const index = new Map<string, number>();

  const evidence = response.sources.map((source, rank): TraceEvidence => {
    let documentIndex = index.get(source.document_id);
    if (documentIndex === undefined) {
      const info = byId.get(source.document_id);
      documentIndex = documents.length;
      index.set(source.document_id, documentIndex);
      documents.push({
        documentId: source.document_id,
        filename: source.filename,
        fileType: info?.file_type ?? null,
        totalPages: info?.total_pages ?? null,
        chunkCount: info?.chunk_count ?? null,
        listed: info !== undefined,
        retrieved: [],
      });
    }
    documents[documentIndex]!.retrieved.push({
      sourceId: source.source_id,
      pageNumber: source.page_number,
      chunkIndex: source.chunk_index,
    });
    return {
      sourceId: source.source_id,
      documentId: source.document_id,
      documentIndex,
      filename: source.filename,
      pageNumber: source.page_number,
      chunkIndex: source.chunk_index,
      score: source.score,
      cited: source.cited,
      rank,
    };
  });

  return { documents, evidence, citedCount: evidence.filter((e) => e.cited).length, response };
}

export const STAGES = ["Documents", "Chunks", "Evidence", "Answer"] as const;
export type StageIndex = 0 | 1 | 2 | 3;
