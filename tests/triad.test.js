import {
  activeTriadToken,
  formatMediumValues,
  insertTriadTerm,
  isResolvedTerm,
  parseMediumValues,
  unresolvedTriadTerms,
} from '../lib/triad/value';
import { dataArrayToObject, dataObjectToArray } from '../lib/utils/fields';

const soil = { label: 'soil', curie: 'ENVO:00001998' };

describe('triad jewel editing', () => {
  test('selecting a term keeps earlier terms and the custom jewel', () => {
    const original = 'cave [ENVO:00000067] + soi:::my fine sediment';
    const token = activeTriadToken(
      original,
      'env_local_scale',
      original.indexOf(':::')
    );
    expect(token.query).toBe('soi');
    expect(insertTriadTerm(original, token, soil).value).toBe(
      'cave [ENVO:00000067] soil [ENVO:00001998]:::my fine sediment'
    );
  });

  test('a space starts the next selected term without an explicit plus', () => {
    const original = 'cave [ENVO:00000067] soi:::local silt';
    const token = activeTriadToken(
      original,
      'env_local_scale',
      original.indexOf(':::')
    );
    expect(token.query).toBe('soi');
    const saved = insertTriadTerm(original, token, soil).value;
    expect(saved).toBe(
      'cave [ENVO:00000067] soil [ENVO:00001998]:::local silt'
    );
    expect(unresolvedTriadTerms(saved, 'env_local_scale')).toEqual([]);
    expect(isResolvedTerm(saved.split(':::')[0])).toBe(false);
  });

  test('never searches the custom part of a jewel', () => {
    const value = 'soil [ENVO:00001998]:::petrous sediment';
    expect(activeTriadToken(value, 'env_medium', value.length)).toBeNull();
  });

  test('each medium value has an independent jewel and search segment', () => {
    const value = 'soil [ENVO:00001998]:::silt | lake wat:::local name | wat';
    const second = activeTriadToken(
      value,
      'env_medium',
      value.indexOf('wat') + 3
    );
    expect(second.query).toBe('lake wat');
    expect(activeTriadToken(value, 'env_medium', value.length).query).toBe(
      'wat'
    );
    expect(
      insertTriadTerm(value, activeTriadToken(value, 'env_medium'), soil).value
    ).toBe(
      'soil [ENVO:00001998]:::silt | lake wat:::local name | soil [ENVO:00001998]'
    );
  });

  test('manual text stays intact and is reported unresolved', () => {
    const value =
      'soil [ENVO:00001998]:::site silt | cave dirt | water [ENVO:00002006]';
    expect(unresolvedTriadTerms(value, 'env_medium')).toEqual(['cave dirt']);
    expect(isResolvedTerm('soil [ENVO:00001998]')).toBe(true);
    expect(isResolvedTerm('cave dirt')).toBe(false);
  });

  test('escaped pipes remain literal within a jewel and never trigger lookup', () => {
    const value = 'soil [ENVO:00001998]:::fine \\| coarse silt | cave dirt';
    expect(parseMediumValues(value)).toEqual([
      'soil [ENVO:00001998]:::fine \\| coarse silt',
      'cave dirt',
    ]);
    expect(
      activeTriadToken(value, 'env_medium', value.indexOf('coarse') + 3)
    ).toBeNull();
    expect(activeTriadToken(value, 'env_medium', value.length).query).toBe(
      'cave dirt'
    );
    expect(unresolvedTriadTerms(value, 'env_medium')).toEqual(['cave dirt']);
  });
});

describe('medium import and export', () => {
  const fields = [
    {
      name: 'env_medium',
      datatype: 'xsd:string',
      multivalued: true,
      triadEditor: true,
    },
    { name: 'unrelated', datatype: 'xsd:string', multivalued: true },
  ];
  const value = 'soil [ENVO:00001998]:::fine silt | cave dirt';

  test('pipe values and their jewels round trip independently', () => {
    const object = dataArrayToObject([value, 'a; b'], fields);
    expect(object).toEqual({
      env_medium: ['soil [ENVO:00001998]:::fine silt', 'cave dirt'],
      unrelated: ['a', 'b'],
    });
    expect(dataObjectToArray(object, fields)).toEqual([value, 'a; b']);
  });

  test('format uses one space on each side of the medium delimiter', () => {
    expect(parseMediumValues('soil| water ')).toEqual(['soil', 'water']);
    expect(formatMediumValues(['soil', 'water'])).toBe('soil | water');
  });

  test('escaped literal pipe survives import and export', () => {
    const escaped = 'soil [ENVO:00001998]:::fine \\| coarse | cave dirt';
    const object = dataArrayToObject([escaped, 'a; b'], fields);
    expect(object.env_medium).toEqual([
      'soil [ENVO:00001998]:::fine \\| coarse',
      'cave dirt',
    ]);
    expect(dataObjectToArray(object, fields)[0]).toBe(escaped);
  });
});
