import TriadSearch from '../lib/triad/search';

describe('triad search lifecycle', () => {
  afterEach(() => jest.useRealTimers());

  test('lexical starts promptly, semantic waits, and custom jewel text is not sent', () => {
    jest.useFakeTimers({ legacyFakeTimers: true });
    const fetcher = jest.fn(() => new Promise(() => {}));
    const search = new TriadSearch(jest.fn(), fetcher);
    search.update('soil', 'env_medium', 4);
    expect(fetcher).not.toHaveBeenCalled();
    jest.advanceTimersByTime(75);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toContain(
      '/lexical?q=soil&field=env_medium&limit=8'
    );
    jest.advanceTimersByTime(324);
    expect(fetcher).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(1);
    expect(fetcher.mock.calls[1][0]).toContain('/semantic?q=soil');

    const jewel = 'soil [ENVO:00001998]:::fine \\| coarse silt';
    search.update(jewel, 'env_medium', jewel.length);
    jest.runOnlyPendingTimers();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(search.token).toBeNull();
    search.update(
      'soil [ENVO:00001998]:::fine silt | lake water',
      'env_medium',
      'soil [ENVO:00001998]:::fine silt | lake water'.length
    );
    jest.advanceTimersByTime(75);
    expect(fetcher.mock.calls[2][0]).toContain('q=lake+water');
    search.cancel();
  });

  test('new input aborts both prior requests and ignores stale responses', async () => {
    jest.useFakeTimers({ legacyFakeTimers: true });
    const pending = [];
    const fetcher = jest.fn((_url, options) => {
      return new Promise((resolve) =>
        pending.push({ resolve, signal: options.signal })
      );
    });
    const onUpdate = jest.fn();
    const search = new TriadSearch(onUpdate, fetcher);
    search.update('cave', 'env_local_scale', 4);
    jest.advanceTimersByTime(75);
    jest.advanceTimersByTime(325);
    expect(pending).toHaveLength(2);
    search.update('cavern', 'env_local_scale', 6);
    expect(pending[0].signal.aborted).toBe(true);
    expect(pending[1].signal.aborted).toBe(true);
    const updatesAfterNewInput = onUpdate.mock.calls.length;
    pending[0].resolve({
      ok: true,
      json: async () => ({
        catalog_version: 'old',
        results: [{ curie: 'ENVO:1' }],
      }),
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(search.sections.lexical).toBeNull();
    expect(onUpdate).toHaveBeenCalledTimes(updatesAfterNewInput);
    search.cancel();
  });

  test('current response keeps catalog version and result provenance', async () => {
    jest.useFakeTimers({ legacyFakeTimers: true });
    const result = {
      curie: 'ENVO:00000067',
      label: 'cave',
      iri: 'http://purl.obolibrary.org/obo/ENVO_00000067',
      source_ontology: 'ENVO',
      definition: 'A subterranean void.',
      match_method: 'exact_label',
      score: 1,
      field_hint: 'possible',
      field_hint_basis: 'local context',
    };
    const fetcher = jest.fn(async () => ({
      ok: true,
      json: async () => ({ catalog_version: 'test-v1', results: [result] }),
    }));
    const search = new TriadSearch(jest.fn(), fetcher);
    search.update('cave', 'env_local_scale', 4);
    jest.advanceTimersByTime(75);
    await Promise.resolve();
    await Promise.resolve();
    expect(search.sections.lexical).toEqual({
      catalogVersion: 'test-v1',
      results: [result],
    });
    search.cancel();
  });
});
