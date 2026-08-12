import { Component, ElementRef, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AnchrynApi } from '../services/anchryn-api';
import { Auth } from '../services/auth';
import { parseAnswer } from './answer-format';
import {
  AnswerResponse,
  Citation,
  DocumentSummary,
  Health,
  Turn,
} from '../models/anchryn.models';

/** How much of the page to show around a highlighted passage. */
const CONTEXT_CHARS = 700;

@Component({
  selector: 'app-chat',
  imports: [FormsModule, DecimalPipe, NgTemplateOutlet],
  templateUrl: './chat.html',
  styleUrl: './chat.css',
})
export class Chat implements OnInit {
  private readonly api = inject(AnchrynApi);
  readonly auth = inject(Auth);
  private readonly scrollPane = viewChild<ElementRef<HTMLElement>>('scrollPane');

  readonly health = signal<Health | null>(null);

  // Library
  readonly documents = signal<DocumentSummary[]>([]);
  readonly uploading = signal(false);
  readonly uploadError = signal<string | null>(null);
  /** null means search every document. */
  readonly scopeId = signal<string | null>(null);

  // Conversation
  readonly turns = signal<Turn[]>([]);
  readonly draft = signal('');
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  // Source viewer
  readonly openCitation = signal<Citation | null>(null);
  readonly pageText = signal<string | null>(null);
  readonly pageLoading = signal(false);

  /** Turn ids whose retrieval panel is expanded. */
  readonly expanded = signal<ReadonlySet<number>>(new Set());

  private nextTurnId = 1;

  readonly ready = computed(() =>
    this.documents().some((doc) => doc.status === 'READY' && doc.chunk_count > 0),
  );

  readonly scopeName = computed(() => {
    const id = this.scopeId();
    if (!id) {
      return 'All documents';
    }
    return this.documents().find((doc) => doc.id === id)?.filename ?? 'All documents';
  });

  /**
   * The cited passage inside its page, trimmed to a readable window.
   *
   * The slice is taken with the offsets the backend stored, so what is
   * highlighted is exactly the text that was retrieved — not a re-search for
   * matching words, which would drift.
   */
  readonly sourceView = computed(() => {
    const citation = this.openCitation();
    const page = this.pageText();
    if (!citation || page === null) {
      return null;
    }

    const start = Math.max(0, citation.char_start - CONTEXT_CHARS);
    const end = Math.min(page.length, citation.char_end + CONTEXT_CHARS);

    return {
      before: page.slice(start, citation.char_start),
      match: page.slice(citation.char_start, citation.char_end),
      after: page.slice(citation.char_end, end),
      trimmedStart: start > 0,
      trimmedEnd: end < page.length,
    };
  });

  ngOnInit(): void {
    this.api.health().subscribe({
      next: (health) => this.health.set(health),
      error: (e: Error) => this.error.set(e.message),
    });
    this.refreshDocuments();
  }

  // ---------------------------------------------------------------- library

  refreshDocuments(): void {
    this.api.listDocuments().subscribe({
      next: (docs) => {
        this.documents.set(docs);
        // A scoped document that has been deleted elsewhere should not leave
        // the search silently pinned to nothing.
        if (this.scopeId() && !docs.some((doc) => doc.id === this.scopeId())) {
          this.scopeId.set(null);
        }
      },
      error: (e: Error) => this.error.set(e.message),
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    this.uploadError.set(null);
    this.uploading.set(true);

    this.api.upload(file).subscribe({
      next: () => {
        this.uploading.set(false);
        this.refreshDocuments();
        input.value = ''; // allow re-uploading the same file
      },
      error: (e: Error) => {
        this.uploading.set(false);
        this.uploadError.set(e.message);
        input.value = '';
      },
    });
  }

  removeDocument(id: string, event: MouseEvent): void {
    event.stopPropagation();
    this.api.deleteDocument(id).subscribe({
      next: () => this.refreshDocuments(),
      error: (e: Error) => this.error.set(e.message),
    });
  }

  scopeTo(id: string | null): void {
    this.scopeId.set(id);
  }

  // ---------------------------------------------------------------- asking

  canSend(): boolean {
    return this.draft().trim().length > 0 && !this.busy();
  }

  send(): void {
    const question = this.draft().trim();
    if (!question || this.busy()) {
      return;
    }

    const turn: Turn = {
      id: this.nextTurnId++,
      question,
      scopedTo: this.scopeId(),
      pending: true,
    };

    this.turns.update((list) => [...list, turn]);
    this.draft.set('');
    this.busy.set(true);
    this.error.set(null);
    this.scrollToBottom();

    this.api.answer(question, this.scopeId()).subscribe({
      next: (answer) => {
        this.replaceTurn(turn.id, {
          answer,
          blocks: parseAnswer(answer.answer, answer.results),
          pending: false,
        });
        this.busy.set(false);
        this.scrollToBottom();
      },
      error: (e: Error) => {
        this.replaceTurn(turn.id, { error: e.message, pending: false });
        this.busy.set(false);
        this.scrollToBottom();
      },
    });
  }

  private replaceTurn(id: number, patch: Partial<Turn>): void {
    this.turns.update((list) =>
      list.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)),
    );
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  clearConversation(): void {
    this.turns.set([]);
    this.closeSource();
  }

  // ---------------------------------------------------------------- answers

  /** The passages the answer actually cited, in citation order. */
  citedSources(answer: AnswerResponse): Citation[] {
    return answer.cited_chunk_ids
      .map((id) => answer.results.find((result) => result.chunk_id === id))
      .filter((result): result is Citation => result !== undefined);
  }

  isCited(answer: AnswerResponse, citation: Citation): boolean {
    return answer.cited_chunk_ids.includes(citation.chunk_id);
  }

  toggleDetails(turnId: number): void {
    this.expanded.update((set) => {
      const next = new Set(set);
      if (next.has(turnId)) {
        next.delete(turnId);
      } else {
        next.add(turnId);
      }
      return next;
    });
  }

  isExpanded(turnId: number): boolean {
    return this.expanded().has(turnId);
  }

  // ---------------------------------------------------------------- source viewer

  openSource(citation: Citation | null): void {
    if (!citation) {
      return;
    }
    this.openCitation.set(citation);
    this.pageText.set(null);
    this.pageLoading.set(true);

    this.api.page(citation.document_id, citation.page_number).subscribe({
      next: (page) => {
        this.pageText.set(page.text);
        this.pageLoading.set(false);
      },
      error: (e: Error) => {
        this.pageLoading.set(false);
        this.error.set(e.message);
        this.closeSource();
      },
    });
  }

  closeSource(): void {
    this.openCitation.set(null);
    this.pageText.set(null);
  }

  // ---------------------------------------------------------------- misc

  scoreClass(similarity: number, threshold: number): string {
    if (similarity >= threshold + 0.15) {
      return 'score-strong';
    }
    if (similarity >= threshold) {
      return 'score-ok';
    }
    return 'score-weak';
  }

  scorePercent(similarity: number): number {
    return Math.max(0, Math.min(100, similarity * 100));
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${Math.round(bytes / 1024)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const pane = this.scrollPane()?.nativeElement;
      if (pane) {
        pane.scrollTop = pane.scrollHeight;
      }
    });
  }
}
