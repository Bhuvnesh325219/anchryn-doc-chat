import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { environment } from '../../environments/environment';
import {
  AnswerResponse,
  AskResponse,
  ChunkSummary,
  DocumentSummary,
  Health,
  PageText,
} from '../models/anchryn.models';

@Injectable({ providedIn: 'root' })
export class AnchrynApi {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api`;

  health(): Observable<Health> {
    return this.http.get<Health>(`${this.base}/health`).pipe(catchError(toMessage));
  }

  listDocuments(): Observable<DocumentSummary[]> {
    return this.http.get<DocumentSummary[]>(`${this.base}/documents`).pipe(catchError(toMessage));
  }

  upload(file: File): Observable<DocumentSummary> {
    const form = new FormData();
    form.append('file', file);
    return this.http
      .post<DocumentSummary>(`${this.base}/documents`, form)
      .pipe(catchError(toMessage));
  }

  deleteDocument(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/documents/${id}`).pipe(catchError(toMessage));
  }

  embedDocument(id: string): Observable<DocumentSummary> {
    return this.http
      .post<DocumentSummary>(`${this.base}/documents/${id}/embed`, {})
      .pipe(catchError(toMessage));
  }

  chunks(id: string): Observable<ChunkSummary[]> {
    return this.http
      .get<ChunkSummary[]>(`${this.base}/documents/${id}/chunks`)
      .pipe(catchError(toMessage));
  }

  /** The extracted text of a page — what a citation's offsets index into. */
  page(documentId: string, pageNumber: number): Observable<PageText> {
    return this.http
      .get<PageText>(`${this.base}/documents/${documentId}/pages/${pageNumber}`)
      .pipe(catchError(toMessage));
  }

  /** Retrieve and answer. */
  answer(question: string, documentId: string | null, topK = 5): Observable<AnswerResponse> {
    return this.http
      .post<AnswerResponse>(`${this.base}/answer`, {
        question,
        document_id: documentId,
        top_k: topK,
      })
      .pipe(catchError(toMessage));
  }

  /** Retrieval only, no model involved. */
  ask(question: string, documentId: string | null, topK = 5): Observable<AskResponse> {
    return this.http
      .post<AskResponse>(`${this.base}/ask`, {
        question,
        document_id: documentId,
        top_k: topK,
      })
      .pipe(catchError(toMessage));
  }
}

/**
 * FastAPI puts its message in `detail`, and validation errors make that an
 * array of objects rather than a string. Both are unwrapped here so components
 * only ever deal with an Error carrying readable text.
 */
function toMessage(response: HttpErrorResponse) {
  const detail = (response.error as { detail?: unknown } | null)?.detail;

  if (typeof detail === 'string') {
    return throwError(() => new Error(detail));
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        const entry = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : '';
        return field ? `${field}: ${entry.msg}` : entry.msg;
      })
      .filter(Boolean);
    return throwError(() => new Error(parts.join('; ') || 'The request was rejected.'));
  }
  if (response.status === 0) {
    return throwError(
      () => new Error('Cannot reach the backend. Is it running on http://localhost:8000?'),
    );
  }
  return throwError(() => new Error(`Request failed with status ${response.status}.`));
}
