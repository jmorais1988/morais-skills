// Particle pool. Every particle is an ordinary splat record appended after the baked
// splats, so it is sorted and drawn with them. Its position is a closed-form function
// of time (origin + velocity * age - gravity), evaluated identically here, for the
// depth sort, and in the vertex shader, so nothing is uploaded per frame.
import { mulberry32, SPLAT_FLOATS } from './engine.js';

export const WORLD_PART = 255;       // part index meaning "world space, no part matrix"
const KIND_PARTICLE = 2;             // value of the kind slot, see sampleChunk
const MAX_PER_EMITTER = 400;

// Record layout, same slots as a baked splat but reused:
// origin.xyz part | velocity.xyz seed | gravity phase life size | colour.rgb size | unused.rgb kind
export function buildParticles(emitters, parts) {
  const specs = emitters.map((e, i) => {
    const part = e.part == null ? null : typeof e.part === 'string' ? parts.find((p) => p.name === e.part) : e.part;
    if (e.part != null && !part) throw new Error(`emitter ${i}: no part named "${e.part}"`);
    const want = Math.round(e.rate * e.life);
    if (want > MAX_PER_EMITTER) console.warn(`emitter ${i}: rate * life = ${want}, pool limited to ${MAX_PER_EMITTER}`);
    return { e, part, count: Math.min(want, MAX_PER_EMITTER) };
  });
  const total = specs.reduce((s, x) => s + x.count, 0), data = new Float32Array(total * SPLAT_FLOATS);
  let o = 0;
  specs.forEach(({ e, part, count }, i) => {
    const rng = mulberry32(5000 + i), v = e.velocity || [0, 0, 0], sp = e.spread || 0, col = e.colour || [1, 1, 1];
    const gain = e.emissive === true ? 1 : e.emissive || 1, size = e.size ?? 0.03, pos = e.pos || [0, 0, 0];
    for (let k = 0; k < count; k++, o += SPLAT_FLOATS) {
      const phase = (k + rng()) / count;   // evenly staggered, so the stream looks continuous from the first frame
      data.set([
        pos[0], pos[1], pos[2], part ? part.index : WORLD_PART,
        v[0] + (rng() * 2 - 1) * sp, v[1] + (rng() * 2 - 1) * sp, v[2] + (rng() * 2 - 1) * sp, rng() * 1000,
        e.gravity || 0, phase, e.life, size,
        col[0] * gain, col[1] * gain, col[2] * gain, size,
        0, 0, 0, KIND_PARTICLE,
      ], o);
    }
  });
  return data;
}

// Writes each particle's position in its part's frame at time t into centers[first * 3 ...].
export function particleCenters(data, centers, first, t) {
  for (let s = 0, j = first * 3; s < data.length; s += SPLAT_FLOATS, j += 3) {
    const life = data[s + 10], age = (((t / life + data[s + 9]) % 1) + 1) % 1 * life;
    centers[j] = data[s] + data[s + 4] * age;
    centers[j + 1] = data[s + 1] + data[s + 5] * age - 0.5 * data[s + 8] * age * age;
    centers[j + 2] = data[s + 2] + data[s + 6] * age;
  }
}
