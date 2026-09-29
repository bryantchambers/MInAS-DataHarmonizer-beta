import { DataHarmonizer, Footer, Toolbar } from '../lib';
import { TRIAD_FIELDS } from '../lib/triad/value';

import 'bootstrap/dist/css/bootstrap.min.css';
import './index.css';

import { menu, getSchema, getExportFormats } from 'schemas';

document.addEventListener('DOMContentLoaded', function () {
  const dhRoot = document.querySelector('#data-harmonizer-grid');
  const dhFooterRoot = document.querySelector('#data-harmonizer-footer');
  const dhToolbarRoot = document.querySelector('#data-harmonizer-toolbar');

  const fieldSettings = Object.fromEntries(
    TRIAD_FIELDS.map((field) => [
      field,
      {
        triadEditor: true,
        getColumn: (_dh, column) => ({
          ...column,
          type: 'dh.triad',
          source: null,
          triadField: field,
        }),
      },
    ])
  );

  const dh = new DataHarmonizer(dhRoot, {
    loadingScreenRoot: document.querySelector('body'),
    fieldSettings,
  });

  new Footer(dhFooterRoot, dh);

  let templatePath;
  if (window.URLSearchParams) {
    let params = new URLSearchParams(location.search);
    templatePath = params.get('template');
  } else {
    templatePath = location.search.split('template=')[1];
  }
  new Toolbar(dhToolbarRoot, dh, menu, {
    templatePath: templatePath,
    releasesURL: 'https://github.com/cidgoh/pathogen-genomics-package/releases',
    getSchema: getSchema,
    getExportFormats: getExportFormats,
  });
});
