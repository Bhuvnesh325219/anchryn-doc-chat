import { Block } from '../chat/answer-format';

/**
 * Wire types, mirroring the FastAPI schemas exactly.
 *
 * Kept in snake_case to match the backend rather than converting at the
 * boundary. A mapping layer here would be one more place for a field to be
 * silently dropped, and these objects are only ever read.
 */

export type DocumentStatus = 'PENDING' | 'PARSING' | 'EMBEDDING' | 'READY' | 'FAILED';

export interface DocumentSummary {
  id: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChunkSummary {
  id: number;
  ordinal: number;
  page_number: number;
  char_start: number;
  char_end: number;
  text: string;
  embedded: boolean;
}

/** A retrieved passage. char_start/char_end index into the page text. */
export interface Citation {
  chunk_id: number;
  document_id: string;
  filename: string;
  page_number: number;
  char_start: number;
  char_end: number;
  text: string;
  similarity: number;
}

export interface AnswerResponse {
  question: string;
  answer: string;
  grounded: boolean;
  cited_chunk_ids: number[];
  results: Citation[];
  best_similarity: number;
  threshold: number;
  model: string;
}

/** Retrieval only, no generation — used by the debug view. */
export interface AskResponse {
  question: string;
  results: Citation[];
  best_similarity: number;
  grounded: boolean;
  threshold: number;
}

export interface PageText {
  page_number: number;
  text: string;
}

export interface Health {
  status: string;
  database: string;
  hf_configured: boolean;
  embedding_model: string;
  embedding_model_loaded: boolean;
}

/** One exchange in the conversation. */
export interface Turn {
  id: number;
  question: string;
  scopedTo: string | null;
  answer?: AnswerResponse;
  /**
   * The answer parsed into renderable blocks. Computed once when the answer
   * arrives rather than in the template, which would re-parse the whole
   * conversation on every change-detection pass.
   */
  blocks?: Block[];
  error?: string;
  pending: boolean;
}

export interface UserProfile {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
}
