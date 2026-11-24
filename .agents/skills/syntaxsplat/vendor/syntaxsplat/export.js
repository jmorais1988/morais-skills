// Export the baked splats as a standard 3D Gaussian Splatting PLY (binary little
// endian), in the parts' current pose. Each splat becomes a thin Gaussian lying in
// its surface plane: long axis along the brush tangent, short axis along the
// bitangent, a very small sigma along the normal.
//
// Coordinates are written as the scene has them: right-handed, +Y up. Capture
// pipelines (COLMAP) are +Y down, so viewers that assume that show the scene
// upside down until it is rotated 180 degrees about X.
import { parts, SPLAT_FLOATS } from './engine.js';

const SH_C0 = 0.28209479177387814;   // colour <-> f_dc scale of the degree-0 spherical harmonic
const SIGMAS_TO_EDGE = 2.8;          // a splat quad's half-extent is about this many sigmas
const NORMAL_SIGMA = 0.15;           // normal-axis sigma as a fraction of the smaller surface sigma
const PEAK_ALPHA = 0.9;              // our dab peaks near 1 but is soft; keeps overlaps from saturating
const PROPS = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3'];

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const logit = (p) => Math.log(p / (1 - p));

// Unit quaternion (w, x, y, z) of the rotation whose columns are the axes t, b, n.
function quatFromAxes(t, b, n, out) {
  const m00 = t[0], m10 = t[1], m20 = t[2], m01 = b[0], m11 = b[1], m21 = b[2], m02 = n[0], m12 = n[1], m22 = n[2];
  const tr = m00 + m11 + m22;
  let w, x, y, z, s;
  if (tr > 0) { s = 0.5 / Math.sqrt(tr + 1); w = 0.25 / s; x = (m21 - m12) * s; y = (m02 - m20) * s; z = (m10 - m01) * s; }
  else if (m00 > m11 && m00 > m22) { s = 2 * Math.sqrt(1 + m00 - m11 - m22); w = (m21 - m12) / s; x = 0.25 * s; y = (m01 + m10) / s; z = (m02 + m20) / s; }
  else if (m11 > m22) { s = 2 * Math.sqrt(1 + m11 - m00 - m22); w = (m02 - m20) / s; x = (m01 + m10) / s; y = 0.25 * s; z = (m12 + m21) / s; }
  else { s = 2 * Math.sqrt(1 + m22 - m00 - m11); w = (m10 - m01) / s; x = (m02 + m20) / s; y = (m12 + m21) / s; z = 0.25 * s; }
  const l = Math.hypot(w, x, y, z) || 1;
  out[0] = w / l; out[1] = x / l; out[2] = y / l; out[3] = z / l;
}

// data: packed baked splats (SPLAT_FLOATS each). size: the page's current Splat size multiplier.
export function buildPly(data, size) {
  const n = data.length / SPLAT_FLOATS, rows = new Float32Array(n * PROPS.length);
  const t = [0, 0, 0], b = [0, 0, 0], nr = [0, 0, 0], q = [0, 0, 0, 0];
  for (let i = 0, o = 0; i < n; i++, o += PROPS.length) {
    const s = i * SPLAT_FLOATS, part = parts[data[s + 3]], M = part.world.elements;
    const x = data[s], y = data[s + 1], z = data[s + 2];
    rows[o] = M[0] * x + M[4] * y + M[8] * z + M[12];
    rows[o + 1] = M[1] * x + M[5] * y + M[9] * z + M[13];
    rows[o + 2] = M[2] * x + M[6] * y + M[10] * z + M[14];
    for (let k = 0; k < 3; k++) {
      nr[k] = M[k] * data[s + 4] + M[4 + k] * data[s + 5] + M[8 + k] * data[s + 6];
      t[k] = M[k] * data[s + 8] + M[4 + k] * data[s + 9] + M[8 + k] * data[s + 10];
    }
    b[0] = nr[1] * t[2] - nr[2] * t[1]; b[1] = nr[2] * t[0] - nr[0] * t[2]; b[2] = nr[0] * t[1] - nr[1] * t[0];
    quatFromAxes(t, b, nr, q);
    const st = data[s + 11] * size / SIGMAS_TO_EDGE, sb = data[s + 15] * size / SIGMAS_TO_EDGE;
    for (let c = 0; c < 3; c++) rows[o + 3 + c] = (clamp01(data[s + 12 + c]) - 0.5) / SH_C0;
    rows[o + 6] = logit(Math.min(0.98, Math.max(0.02, PEAK_ALPHA * part.opacity)));
    rows[o + 7] = Math.log(st); rows[o + 8] = Math.log(sb); rows[o + 9] = Math.log(Math.min(st, sb) * NORMAL_SIGMA);
    rows[o + 10] = q[0]; rows[o + 11] = q[1]; rows[o + 12] = q[2]; rows[o + 13] = q[3];
  }
  const header = `ply\nformat binary_little_endian 1.0\nelement vertex ${n}\n${PROPS.map((p) => `property float ${p}\n`).join('')}end_header\n`;
  return new Blob([header, rows], { type: 'application/octet-stream' });
}

export function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}
