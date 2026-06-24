# Third-party components

This site vendors the following third-party assets locally (no third-party
requests are made at runtime). Their licenses are reproduced/linked below.

| Component | Version | License | Location |
|-----------|---------|---------|----------|
| React | 18.3.1 | MIT | `vendor/react.production.min.js` |
| ReactDOM | 18.3.1 | MIT | `vendor/react-dom.production.min.js` |
| globe.gl (incl. three.js) | 2.32.0 | MIT | `vendor/globe.gl.min.js` |
| IBM Plex (Sans / Mono / Serif) | latin subset | SIL Open Font License 1.1 | `fonts/*.woff2` |
| Natural Earth Admin 0 (50m) | — | Public domain | `data/ne_50m_admin_0_countries.json` |

- React / ReactDOM — MIT License, © Meta Platforms, Inc. and affiliates — https://github.com/facebook/react/blob/main/LICENSE
- globe.gl — MIT License, © Vasco Asturiano — https://github.com/vasturiano/globe.gl/blob/master/LICENSE
- three.js (bundled in globe.gl) — MIT License — https://github.com/mrdoob/three.js/blob/dev/LICENSE
- IBM Plex — SIL Open Font License 1.1, © IBM Corp. — https://github.com/IBM/plex/blob/master/LICENSE.txt
- Natural Earth — public domain — https://www.naturalearthdata.com/about/terms-of-use/

Simulation outputs in `simulation_data/` and the derived `data/explorer_data.json`
are products of the Global Unbreakable model and are not third-party assets.
