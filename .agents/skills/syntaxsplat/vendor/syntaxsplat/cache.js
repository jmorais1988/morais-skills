// Bake cache in IndexedDB. A baked scene is a few tens of MB of floats that take
// seconds to minutes to produce, and the result only depends on the scene file and
// engine.js, so the key hashes both texts. Every function degrades to "no cache"
// when IndexedDB is missing or blocked (private windows, file restrictions).
import { SPLAT_FLOATS } from './engine.js';

const DB_NAME = 'splattest-bake', STORE = 'bakes';

// cyrb53: small, fast, good enough to notice an edited file. Not for security.
function hashText(s) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
}

const prefix = (scene) => scene + '|';
const sceneRange = (scene) => IDBKeyRange.bound(prefix(scene), prefix(scene) + '￿');
const wrap = (req) => new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); });
const done = (tx) => new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = tx.onabort = () => rej(tx.error); });

function open() {
  const req = indexedDB.open(DB_NAME, 1);
  req.onupgradeneeded = () => req.result.createObjectStore(STORE);
  return wrap(req);
}

// Key = scene id + hash of the scene text + hash of engine.js + splat layout.
// The fetch revalidates, which also refreshes the browser's HTTP cache entry, so the
// scene module imported right after (and the workers) see the same text that was hashed.
// Returns null when the sources cannot be fetched, which disables caching.
export async function bakeKey(scene) {
  try {
    const [s, e] = await Promise.all([`./scenes/${scene}.js`, './engine.js'].map((u) => fetch(u, { cache: 'no-cache' }).then((r) => (r.ok ? r.text() : Promise.reject(new Error(u))))));
    return `${prefix(scene)}${hashText(s)}|${hashText(e)}|${SPLAT_FLOATS}`;
  } catch { return null; }
}

// -> { buf: Float32Array } or null
export async function loadBake(key) {
  if (!key) return null;
  try {
    const db = await open();
    const hit = await wrap(db.transaction(STORE).objectStore(STORE).get(key));
    db.close();
    return hit && hit.buf instanceof Float32Array ? hit : null;
  } catch { return null; }
}

// Replaces every older entry of the same scene, so edits do not pile up in storage.
export async function saveBake(key, scene, value) {
  if (!key) return;
  try {
    const db = await open();
    const tx = db.transaction(STORE, 'readwrite'), os = tx.objectStore(STORE);
    os.delete(sceneRange(scene));
    os.put(value, key);
    await done(tx);
    db.close();
  } catch (e) { console.warn('bake cache not saved:', e.message || e); }
}

export async function clearBake(scene) {
  try {
    const db = await open();
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).delete(sceneRange(scene));
    await done(tx);
    db.close();
  } catch { /* nothing cached, or no IndexedDB */ }
}
