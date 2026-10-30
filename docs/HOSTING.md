# Global Resilience Explorer: hosting notes

`VERSION.txt` (next to this file in the package) records the commit it was built from and when.

## What this is

A **static website**: plain HTML, JavaScript, JSON data and font files. 

The model results are computed offline beforehand and ship as JSON files in `site/data/`.
The browser downloads them and does all the rendering itself (a 3D globe drawn with WebGL).

## Publishing

1. Copy **the contents of `site/`** to any location on a static web server.
2. Point the URL at that folder. `index.html` is the entry page.

All paths inside the site are **relative**, so it should work at a domain root
or in a subfolder


### Contents (~6.7 MB, ~150 files)

```
site/
├── index.html            entry page
├── app.js                application code
├── vendor/               React, ReactDOM, globe.gl (minified, MIT-licensed)
├── fonts/                IBM Plex .woff2 (SIL Open Font License)
└── data/
    ├── explorer_data.json      baseline model results
    ├── wb_adm0.json            country shapes from official WBG boundaries
    ├── wb_borders.json         borders / coastlines from official WBG boundaries
    └── policies/               one JSON per country + manifest.json (loaded on demand)
```

## Updates

Updates only happen when the model results or the interface change. Each release is a
full replacement.

## Licences

Third-party components and their licences are listed in `THIRD_PARTY_LICENSES.md` (included).
