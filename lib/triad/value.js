export const TRIAD_FIELDS = [
  'env_broad_scale',
  'env_local_scale',
  'env_medium',
];

const CURIE = '[A-Za-z][A-Za-z0-9_.-]*:[^\\]\\s]+';
const CURIE_TOKEN = new RegExp(`^[^\\[\\]]+ \\[${CURIE}\\]$`);
const TERM_PREFIX = new RegExp(`^([^\\[\\]]+?) \\[${CURIE}\\](?=\\s|$)`);
const TERM_END = new RegExp(`\\[${CURIE}\\](?=\\s|$)`, 'g');

function isEscaped(text, index) {
  let slashes = 0;
  for (let i = index - 1; i >= 0 && text[i] === '\\'; i--) slashes++;
  return slashes % 2 === 1;
}

function mediumRanges(text) {
  const ranges = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '|' && !isEscaped(text, i)) {
      ranges.push({ start, end: i });
      start = i + 1;
    }
  }
  ranges.push({ start, end: text.length });
  return ranges;
}

export function isResolvedTerm(value) {
  return CURIE_TOKEN.test(value.trim());
}

// Each medium value has its own jewel. The first ::: within that value ends
// ontology lookup, so user-supplied text is never sent to the search API.
export function activeTriadToken(value, field, caret = value.length) {
  const text = String(value || '');
  const position = Math.max(0, Math.min(caret, text.length));
  const range =
    field === 'env_medium'
      ? mediumRanges(text).find(
          ({ start, end }) => start <= position && position <= end
        )
      : { start: 0, end: text.length };
  if (!range) return null;
  const { start: valueStart, end: valueEnd } = range;
  const jewel = text.indexOf(':::', valueStart);
  const ontologyEnd = jewel < 0 || jewel >= valueEnd ? valueEnd : jewel;
  if (position > ontologyEnd) return null;

  let priorTermEnd = -1;
  for (const match of text.slice(valueStart, position).matchAll(TERM_END)) {
    priorTermEnd = valueStart + match.index + match[0].length;
  }
  const tokenStart = priorTermEnd < 0 ? valueStart : priorTermEnd;
  const raw = text.slice(tokenStart, ontologyEnd);
  const query = raw.replace(/^\s*\+\s*/, '').trim();
  if (!query || isResolvedTerm(query)) return null;
  return {
    query,
    start: tokenStart,
    end: ontologyEnd,
    previousTerm: priorTermEnd >= 0,
  };
}

export function insertTriadTerm(value, token, result) {
  const text = String(value || '');
  const replacement = `${result.label} [${result.curie}]`;
  const before = text.slice(0, token.start);
  const after = text.slice(token.end);
  const original = text.slice(token.start, token.end);
  const leading = token.previousTerm ? ' ' : /^\s*/.exec(original)[0];
  const trailing = /\s*$/.exec(original)[0];
  const inserted = `${leading}${replacement}${trailing}`;
  return {
    value: before + inserted + after,
    caret: before.length + inserted.length,
  };
}

export function unresolvedTriadTerms(value, field) {
  const text = String(value || '');
  const parts = field === 'env_medium' ? parseMediumValues(text) : [text];
  return parts.flatMap((part) => {
    let remaining = part.split(':::')[0].trim();
    while (remaining) {
      remaining = remaining.replace(/^\+\s*/, '');
      const match = TERM_PREFIX.exec(remaining);
      if (!match) break;
      remaining = remaining.slice(match[0].length).trimStart();
    }
    return remaining ? [remaining] : [];
  });
}

export function parseMediumValues(value) {
  const text = String(value || '');
  return mediumRanges(text)
    .map(({ start, end }) => text.slice(start, end).trim())
    .filter(Boolean);
}

export function formatMediumValues(values) {
  return values
    .map((part) => String(part).trim())
    .filter(Boolean)
    .join(' | ');
}
