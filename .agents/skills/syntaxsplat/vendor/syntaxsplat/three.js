// Single place the three.js URL lives. Workers cannot use the page's import map,
// so engine code imports from here. Must match the "three" entry in index.html.
export * from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
