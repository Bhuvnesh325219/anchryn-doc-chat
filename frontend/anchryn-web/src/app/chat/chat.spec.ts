import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { Chat } from './chat';
import { AnswerResponse, Citation } from '../models/anchryn.models';

function citation(chunkId: number, similarity = 0.8): Citation {
  return {
    chunk_id: chunkId,
    document_id: 'doc-1',
    filename: 'handbook.pdf',
    page_number: 2,
    char_start: 10,
    char_end: 20,
    text: 'passage text',
    similarity,
  };
}

function answer(text: string, results: Citation[], citedIds: number[]): AnswerResponse {
  return {
    question: 'q',
    answer: text,
    grounded: true,
    cited_chunk_ids: citedIds,
    results,
    best_similarity: 0.8,
    threshold: 0.45,
    model: 'test-model',
  };
}

describe('Chat', () => {
  let component: Chat;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Chat],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    component = TestBed.createComponent(Chat).componentInstance;
  });

  it('lists cited sources in citation order, not retrieval order', () => {
    const results = [citation(11), citation(22), citation(33)];
    const sources = component.citedSources(answer('[3] then [1]', results, [33, 11]));

    expect(sources.map((s) => s.chunk_id)).toEqual([33, 11]);
  });

  it('grades scores against the threshold', () => {
    expect(component.scoreClass(0.9, 0.45)).toBe('score-strong');
    expect(component.scoreClass(0.5, 0.45)).toBe('score-ok');
    expect(component.scoreClass(0.3, 0.45)).toBe('score-weak');
  });
});
