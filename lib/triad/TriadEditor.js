import Handsontable from 'handsontable';
import { insertTriadTerm, unresolvedTriadTerms } from './value';
import TriadSearch from './search';

export function triadRenderer(
  instance,
  td,
  row,
  col,
  prop,
  value,
  cellProperties
) {
  Handsontable.renderers.TextRenderer(
    instance,
    td,
    row,
    col,
    prop,
    value,
    cellProperties
  );
  const unresolved = unresolvedTriadTerms(value, cellProperties.triadField);
  td.classList.toggle('dh-triad-unresolved', unresolved.length > 0);
  td.title = unresolved.length
    ? `Unresolved free text: ${unresolved.join('; ')}`
    : '';
  if (unresolved.length) {
    const badge = td.ownerDocument.createElement('span');
    badge.className = 'dh-triad-badge';
    badge.textContent = 'unresolved';
    badge.setAttribute('aria-label', td.title);
    td.appendChild(badge);
  }
}

export default class TriadEditor extends Handsontable.editors.TextEditor {
  createElements() {
    super.createElements();
    const doc = this.hot.rootDocument;
    this.dropdown = doc.createElement('div');
    this.dropdown.className = 'dh-triad-dropdown';
    this.dropdown.id = `dh-triad-dropdown-${Math.random()
      .toString(36)
      .slice(2)}`;
    this.dropdown.setAttribute('role', 'listbox');
    this.dropdown.setAttribute('aria-label', 'Triad term suggestions');
    this.dropdown.setAttribute('aria-live', 'polite');
    this.dropdown.hidden = true;
    this.dropdown.addEventListener('mousedown', (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    doc.body.appendChild(this.dropdown);
    this.TEXTAREA.setAttribute('aria-autocomplete', 'list');
    this.TEXTAREA.setAttribute('aria-controls', this.dropdown.id);
    this.TEXTAREA.setAttribute('aria-expanded', 'false');
    this.TEXTAREA.addEventListener('input', () => this.search());
    this.searchState = new TriadSearch((state) => {
      this.token = state.token;
      this.sections = state.sections;
      if (state.token) this.renderResults();
      else this.hideDropdown();
    });
    this.hot.addHook('afterDestroy', () => {
      this.searchState.cancel();
      this.dropdown.remove();
    });
  }

  open() {
    super.open();
    this.activeResults = [];
    this.activeIndex = -1;
    this.sections = { lexical: null, semantic: null };
    this.addHook('beforeKeyDown', (event) => this.handleKeyDown(event));
  }

  beginEditing(newInitialValue, event) {
    super.beginEditing(newInitialValue, event);
    // Handsontable can seed the first typed character programmatically, without
    // firing an input event. Focus has placed the caret by this point.
    this.search();
  }

  close() {
    this.searchState.cancel();
    this.hideDropdown();
    this.removeHooksByKey('beforeKeyDown');
    super.close();
  }

  search() {
    this.activeIndex = -1;
    this.searchState.update(
      this.getValue(),
      this.cellProperties.triadField,
      this.TEXTAREA.selectionStart
    );
  }

  renderResults() {
    const doc = this.hot.rootDocument;
    this.dropdown.replaceChildren();
    this.activeResults = [];
    const heading = doc.createElement('div');
    heading.className = 'dh-triad-instructions';
    heading.textContent =
      'Provisional, unreviewed suggestions. Similarity ranks retrieval; it is not confidence or mapping approval. Type a space for another term (" + " also works), or ":::" for your own detail.';
    this.dropdown.appendChild(heading);
    for (const kind of ['lexical', 'semantic']) {
      const section = doc.createElement('section');
      section.setAttribute('role', 'group');
      const title = doc.createElement('h6');
      title.textContent =
        kind === 'lexical' ? 'Lexical matches' : 'Semantic matches';
      section.appendChild(title);
      const state = this.sections[kind];
      if (state?.error) {
        const message = doc.createElement('div');
        message.textContent = `${kind} search unavailable: ${state.error}`;
        section.appendChild(message);
      } else if (state?.results?.length) {
        let rank = 0;
        for (const result of state.results) {
          if (!result || !result.curie || !result.label) continue;
          rank += 1;
          const button = doc.createElement('button');
          button.type = 'button';
          button.className = 'dh-triad-result';
          button.setAttribute('role', 'option');
          button.id = `${this.dropdown.id}-option-${this.activeResults.length}`;
          const label = doc.createElement('strong');
          label.textContent = `${result.label} [${result.curie}]`;
          button.appendChild(label);
          const details = doc.createElement('small');
          const similarity =
            result.score !== null &&
            result.score !== undefined &&
            Number.isFinite(Number(result.score))
              ? ` · similarity ${Number(result.score).toFixed(3)}`
              : '';
          details.textContent = `${
            result.source_ontology || 'Unknown ontology'
          } · ${result.match_method || kind} · ${
            kind === 'semantic'
              ? `semantic retrieval${similarity}`
              : `lexical rank ${rank}`
          }`;
          button.appendChild(details);
          if (result.definition) {
            const definition = doc.createElement('span');
            definition.textContent = result.definition;
            button.appendChild(definition);
          }
          const fit = doc.createElement('small');
          fit.textContent = `Field fit hint (soft): ${
            result.field_hint || 'unspecified'
          }${
            result.field_hint_basis ? ` (${result.field_hint_basis})` : ''
          } · ${result.iri || 'IRI unavailable'}`;
          button.appendChild(fit);
          button.addEventListener('click', () => this.selectResult(result));
          section.appendChild(button);
          this.activeResults.push(result);
        }
      } else {
        const message = doc.createElement('div');
        message.textContent = state ? 'No matches' : 'Searching…';
        section.appendChild(message);
      }
      if (state?.catalogVersion) {
        const version = doc.createElement('small');
        version.textContent = `Catalog ${state.catalogVersion}`;
        section.appendChild(version);
      }
      this.dropdown.appendChild(section);
    }
    this.positionDropdown();
    this.dropdown.hidden = false;
    this.TEXTAREA.setAttribute('aria-expanded', 'true');
    this.highlightActive();
  }

  positionDropdown() {
    const rect = this.TD.getBoundingClientRect();
    this.dropdown.style.left = `${Math.max(0, rect.left)}px`;
    this.dropdown.style.top = `${Math.min(
      rect.bottom,
      window.innerHeight - 80
    )}px`;
    this.dropdown.style.width = `${Math.max(340, rect.width)}px`;
  }

  hideDropdown() {
    this.dropdown.hidden = true;
    this.TEXTAREA.setAttribute('aria-expanded', 'false');
    this.TEXTAREA.removeAttribute('aria-activedescendant');
  }

  highlightActive() {
    const buttons = this.dropdown.querySelectorAll('.dh-triad-result');
    buttons.forEach((button, index) => {
      const active = index === this.activeIndex;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
      if (active) {
        this.TEXTAREA.setAttribute('aria-activedescendant', button.id);
        button.scrollIntoView({ block: 'nearest' });
      }
    });
    if (this.activeIndex < 0)
      this.TEXTAREA.removeAttribute('aria-activedescendant');
  }

  handleKeyDown(event) {
    if (this.dropdown.hidden) return;
    if (event.key === 'Escape') {
      this.searchState.cancel();
      this.hideDropdown();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!this.activeResults.length) return;
      const step = event.key === 'ArrowDown' ? 1 : -1;
      this.activeIndex =
        (this.activeIndex + step + this.activeResults.length) %
        this.activeResults.length;
      this.highlightActive();
    } else if (event.key === 'Enter' && this.activeIndex >= 0) {
      this.selectResult(this.activeResults[this.activeIndex]);
    } else {
      return;
    }
    event.preventDefault();
    Handsontable.dom.stopImmediatePropagation(event);
  }

  selectResult(result) {
    if (!this.token) return;
    const inserted = insertTriadTerm(this.getValue(), this.token, result);
    this.setValue(inserted.value);
    this.TEXTAREA.focus();
    this.TEXTAREA.setSelectionRange(inserted.caret, inserted.caret);
    this.searchState.cancel();
    this.hideDropdown();
  }
}
