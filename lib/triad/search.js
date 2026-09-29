import { activeTriadToken } from './value';

const API_ROOT = '/api/v1/mvp/triad';
const RESULT_LIMIT = 8;
const LEXICAL_DELAY_MS = 75;
const SEMANTIC_DELAY_MS = 400;

export default class TriadSearch {
  constructor(onUpdate, fetcher = (...args) => fetch(...args)) {
    this.onUpdate = onUpdate;
    this.fetcher = fetcher;
    this.requestId = 0;
  }

  cancel() {
    this.requestId += 1;
    clearTimeout(this.lexicalTimer);
    clearTimeout(this.semanticTimer);
    if (this.lexicalController) this.lexicalController.abort();
    if (this.semanticController) this.semanticController.abort();
    this.lexicalController = null;
    this.semanticController = null;
  }

  update(value, field, caret) {
    this.cancel();
    this.token = activeTriadToken(value, field, caret);
    this.sections = { lexical: null, semantic: null };
    this.onUpdate(this);
    if (!this.token) return;
    const requestId = this.requestId;
    const query = this.token.query;
    this.lexicalTimer = setTimeout(
      () => this.request('lexical', query, field, requestId),
      LEXICAL_DELAY_MS
    );
    this.semanticTimer = setTimeout(
      () => this.request('semantic', query, field, requestId),
      SEMANTIC_DELAY_MS
    );
  }

  async request(kind, query, field, requestId) {
    const controller = new AbortController();
    this[`${kind}Controller`] = controller;
    const params = new URLSearchParams({
      q: query,
      field,
      limit: String(RESULT_LIMIT),
    });
    try {
      const response = await this.fetcher(`${API_ROOT}/${kind}?${params}`, {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (requestId !== this.requestId) return;
      if (!payload || !Array.isArray(payload.results)) {
        throw new Error('Invalid triad response');
      }
      this.sections[kind] = {
        results: payload.results,
        catalogVersion: payload.catalog_version,
      };
    } catch (error) {
      if (requestId !== this.requestId || error.name === 'AbortError') return;
      this.sections[kind] = { error: error.message };
    }
    if (requestId === this.requestId) this.onUpdate(this);
  }
}
