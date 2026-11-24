// Bake worker: builds the same scene as the page, then samples the chunks it is handed.
import { parts, state, finalizeRest, sampleChunk, mulberry32 } from './engine.js';

onmessage = async (e) => {
  if (e.data.scene) {
    const mod = await import(`./scenes/${e.data.scene}.js`);
    state.cfg = mod.default();
    finalizeRest();
    postMessage({ ready: true });
    return;
  }
  const t = e.data.task, out = [];
  sampleChunk(parts[t.part], t.count, mulberry32(t.seed), out);
  const buf = new Float32Array(out);
  postMessage({ id: t.id, buf }, [buf.buffer]);
};
