/**
 * Turning an answer into renderable structure.
 *
 * The result is *data*, never HTML. The answer is model output, so building
 * markup from it would be the one place this app could be persuaded to render
 * something it should not. The template walks these types and emits real
 * elements, which means no sanitiser is involved and nothing can slip through.
 *
 * Only the small slice of Markdown the model is asked for is supported:
 * paragraphs, bullet and numbered lists, bold, inline code — plus the [n]
 * citation markers, which become buttons.
 */

import { Citation } from '../models/anchryn.models';

export type Inline =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'code'; value: string }
  | { kind: 'cite'; index: number; citation: Citation | null };

export type Block =
  | { kind: 'para'; inlines: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] };

const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;

/** Matches, in one pass: **bold**, `code`, [1]. */
const INLINE_PATTERN = /\*\*(.+?)\*\*|`([^`]+?)`|\[(\d+)\]/g;

export function parseAnswer(text: string, results: Citation[]): Block[] {
  const blocks: Block[] = [];

  for (const raw of text.split(/\n{2,}/)) {
    const lines = raw.split('\n').filter((line) => line.trim().length > 0);
    if (!lines.length) {
      continue;
    }

    const bulleted = lines.every((line) => BULLET.test(line));
    const numbered = !bulleted && lines.every((line) => NUMBERED.test(line));

    if (bulleted || numbered) {
      blocks.push({
        kind: 'list',
        ordered: numbered,
        items: lines.map((line) =>
          parseInlines(line.replace(bulleted ? BULLET : NUMBERED, ''), results),
        ),
      });
      continue;
    }

    // A list that the model prefixed with a lead-in line: split it so the
    // lead-in reads as prose rather than becoming a stray bullet.
    const firstItem = lines.findIndex((line) => BULLET.test(line) || NUMBERED.test(line));
    if (firstItem > 0) {
      blocks.push({
        kind: 'para',
        inlines: parseInlines(lines.slice(0, firstItem).join(' '), results),
      });
      const itemLines = lines.slice(firstItem);
      const ordered = NUMBERED.test(itemLines[0]);
      blocks.push({
        kind: 'list',
        ordered,
        items: itemLines.map((line) =>
          parseInlines(line.replace(ordered ? NUMBERED : BULLET, ''), results),
        ),
      });
      continue;
    }

    // Single newlines inside a paragraph are wrapping, not structure.
    blocks.push({ kind: 'para', inlines: parseInlines(lines.join(' '), results) });
  }

  return blocks;
}

export function parseInlines(text: string, results: Citation[]): Inline[] {
  const inlines: Inline[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  INLINE_PATTERN.lastIndex = 0;
  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > cursor) {
      inlines.push({ kind: 'text', value: text.slice(cursor, match.index) });
    }

    const [, bold, code, citation] = match;
    if (bold !== undefined) {
      inlines.push({ kind: 'bold', value: bold });
    } else if (code !== undefined) {
      inlines.push({ kind: 'code', value: code });
    } else {
      const index = Number(citation);
      inlines.push({
        kind: 'cite',
        index,
        // Out of range means the model invented the reference. Left null so the
        // UI can show it as unresolvable rather than pointing somewhere wrong.
        citation: results[index - 1] ?? null,
      });
    }

    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) {
    inlines.push({ kind: 'text', value: text.slice(cursor) });
  }
  return inlines;
}
