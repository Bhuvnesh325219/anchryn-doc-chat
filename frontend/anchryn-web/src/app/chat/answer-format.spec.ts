import { Block, Inline, parseAnswer, parseInlines } from './answer-format';
import { Citation } from '../models/anchryn.models';

function citation(chunkId: number): Citation {
  return {
    chunk_id: chunkId,
    document_id: 'doc-1',
    filename: 'handbook.pdf',
    page_number: 2,
    char_start: 0,
    char_end: 5,
    text: 'passage',
    similarity: 0.8,
  };
}

const RESULTS = [citation(11), citation(22), citation(33)];

function text(inlines: Inline[]): string {
  return inlines.map((i) => ('value' in i ? i.value : `[${i.index}]`)).join('');
}

describe('parseInlines', () => {
  it('splits bold, code and citations out of prose', () => {
    const inlines = parseInlines('Set **timeout** to `30s` per the policy [2].', RESULTS);

    expect(inlines.map((i) => i.kind)).toEqual(['text', 'bold', 'text', 'code', 'text', 'cite', 'text']);
  });

  it('resolves a citation marker to the matching passage', () => {
    const inlines = parseInlines('Claim [3].', RESULTS);
    const cite = inlines.find((i) => i.kind === 'cite') as { citation: Citation | null };

    expect(cite.citation?.chunk_id).toBe(33);
  });

  it('leaves a fabricated marker unresolved', () => {
    // Pointing it somewhere would be worse than showing it as a dead reference.
    const inlines = parseInlines('Claim [9].', RESULTS);
    const cite = inlines.find((i) => i.kind === 'cite') as { citation: Citation | null };

    expect(cite.citation).toBeNull();
  });

  it('keeps plain text intact', () => {
    expect(parseInlines('No markup here.', RESULTS)).toEqual([
      { kind: 'text', value: 'No markup here.' },
    ]);
  });

  it('does not lose characters', () => {
    const source = 'A **b** c `d` e [1] f';
    expect(text(parseInlines(source, RESULTS))).toBe(source.replace(/\*\*|`/g, ''));
  });
});

describe('parseAnswer', () => {
  it('separates paragraphs', () => {
    const blocks = parseAnswer('First paragraph.\n\nSecond paragraph.', RESULTS);

    expect(blocks.length).toBe(2);
    expect(blocks.every((b) => b.kind === 'para')).toBeTrue();
  });

  it('treats a single newline as wrapping, not a new paragraph', () => {
    const blocks = parseAnswer('One sentence\nwrapped oddly.', RESULTS);

    expect(blocks.length).toBe(1);
    expect(text((blocks[0] as { inlines: Inline[] }).inlines)).toBe('One sentence wrapped oddly.');
  });

  it('recognises a bulleted list', () => {
    const blocks = parseAnswer('- first\n- second\n- third', RESULTS);

    expect(blocks.length).toBe(1);
    const list = blocks[0] as Extract<Block, { kind: 'list' }>;
    expect(list.kind).toBe('list');
    expect(list.ordered).toBeFalse();
    expect(list.items.length).toBe(3);
    expect(text(list.items[0])).toBe('first');
  });

  it('recognises a numbered list', () => {
    const blocks = parseAnswer('1. open settings\n2. choose reset', RESULTS);
    const list = blocks[0] as Extract<Block, { kind: 'list' }>;

    expect(list.ordered).toBeTrue();
    expect(list.items.length).toBe(2);
  });

  it('splits a lead-in line from the list that follows it', () => {
    // Models routinely write the intro on the same block as the bullets. Without
    // this the intro would render as a stray bullet point.
    const blocks = parseAnswer('There are two steps:\n- open settings\n- choose reset', RESULTS);

    expect(blocks.length).toBe(2);
    expect(blocks[0].kind).toBe('para');
    expect(blocks[1].kind).toBe('list');
    expect((blocks[1] as Extract<Block, { kind: 'list' }>).items.length).toBe(2);
  });

  it('keeps citations working inside list items', () => {
    const blocks = parseAnswer('- files kept ninety days [1]\n- then deleted [2]', RESULTS);
    const list = blocks[0] as Extract<Block, { kind: 'list' }>;

    const firstCite = list.items[0].find((i) => i.kind === 'cite') as { citation: Citation | null };
    expect(firstCite.citation?.chunk_id).toBe(11);
  });

  it('ignores blank blocks', () => {
    expect(parseAnswer('\n\n\n', RESULTS)).toEqual([]);
    expect(parseAnswer('', RESULTS)).toEqual([]);
  });

  it('handles the real shape the model produces', () => {
    // Captured verbatim from a live answer: a lead-in sentence, then bullets,
    // with the citation on the final item.
    const blocks = parseAnswer(
      'To reset your password, follow these steps:\n' +
        '- Open account settings.\n' +
        '- Choose Reset Password.\n' +
        '- A confirmation email will arrive within five minutes.\n' +
        '- Links expire after one hour. [1]',
      RESULTS,
    );

    expect(blocks.length).toBe(2);
    expect(blocks[0].kind).toBe('para');
    expect(text((blocks[0] as { inlines: Inline[] }).inlines)).toBe(
      'To reset your password, follow these steps:',
    );

    const list = blocks[1] as Extract<Block, { kind: 'list' }>;
    expect(list.ordered).toBeFalse();
    expect(list.items.length).toBe(4);
    expect(text(list.items[0])).toBe('Open account settings.');
    // The citation on the last bullet must still resolve.
    const cite = list.items[3].find((i) => i.kind === 'cite') as { citation: Citation | null };
    expect(cite.citation?.chunk_id).toBe(11);
  });

  it('handles a plain one-line answer', () => {
    const blocks = parseAnswer('Files are kept for ninety days [1].', RESULTS);

    expect(blocks.length).toBe(1);
    expect(blocks[0].kind).toBe('para');
  });
});
