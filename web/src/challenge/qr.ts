// A small QR code encoder written from ISO/IEC 18004:2015: byte mode, error correction level M,
// versions 1 to 10 (up to 213 bytes, plenty for the phone link). No dependency, no canvas: it returns
// the module matrix and an SVG path.

const EC_M = 0b00; // format bits of level M (L = 01, M = 00, Q = 11, H = 10)

/** Per version: [ECC codewords per block, blocks in group 1, data codewords per group-1 block, blocks in group 2]. */
const BLOCKS_M: [number, number, number, number][] = [
  [10, 1, 16, 0],
  [16, 1, 28, 0],
  [26, 1, 44, 0],
  [18, 2, 32, 0],
  [24, 2, 43, 0],
  [16, 4, 27, 0],
  [18, 4, 31, 0],
  [22, 2, 38, 2],
  [22, 3, 36, 2],
  [26, 4, 43, 1],
];

const ALIGN: number[][] = [[], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];

// ---------------------------------------------------------------- Reed-Solomon over GF(256), poly 0x11d

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
}

const mul = (a: number, b: number) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

/** The generator polynomial (x - a^0)(x - a^1)...(x - a^(n-1)), highest degree first, leading 1 dropped. */
function generator(n: number): number[] {
  let poly = [1];
  for (let i = 0; i < n; i++) {
    const next = new Array<number>(poly.length + 1).fill(0);
    poly.forEach((c, j) => {
      next[j] ^= c;
      next[j + 1] ^= mul(c, EXP[i]);
    });
    poly = next;
  }
  return poly.slice(1);
}

/** The n error correction codewords of one block: the remainder of data * x^n divided by the generator. */
export function reedSolomon(data: number[], n: number): number[] {
  const gen = generator(n);
  const rem = new Array<number>(n).fill(0);
  for (const byte of data) {
    const factor = byte ^ rem[0];
    rem.shift();
    rem.push(0);
    gen.forEach((g, i) => (rem[i] ^= mul(g, factor)));
  }
  return rem;
}

// ---------------------------------------------------------------- format and version information

function bch(value: number, poly: number, polyBits: number, dataBits: number): number {
  let rem = value << (polyBits - 1);
  for (let i = dataBits + polyBits - 2; i >= polyBits - 1; i--) if ((rem >> i) & 1) rem ^= poly << (i - polyBits + 1);
  return (value << (polyBits - 1)) | rem;
}

/** 15 format bits for level M and a mask, already XORed with the 101010000010010 mask pattern. */
export function formatBits(mask: number): number {
  return bch((EC_M << 3) | mask, 0x537, 11, 5) ^ 0x5412;
}

/** 18 version bits (versions 7 and up). */
export function versionBits(version: number): number {
  return bch(version, 0x1f25, 13, 6);
}

// ---------------------------------------------------------------- matrix

type Grid = { size: number; dark: boolean[][]; fixed: boolean[][] };

function newGrid(version: number): Grid {
  const size = 17 + 4 * version;
  return {
    size,
    dark: Array.from({ length: size }, () => new Array<boolean>(size).fill(false)),
    fixed: Array.from({ length: size }, () => new Array<boolean>(size).fill(false)),
  };
}

function setFixed(g: Grid, x: number, y: number, dark: boolean) {
  g.dark[y][x] = dark;
  g.fixed[y][x] = true;
}

function drawFunctionPatterns(g: Grid, version: number) {
  const { size } = g;
  for (let i = 0; i < size; i++) {
    setFixed(g, 6, i, i % 2 === 0);
    setFixed(g, i, 6, i % 2 === 0);
  }
  // three finders with their separators
  for (const [cx, cy] of [
    [3, 3],
    [size - 4, 3],
    [3, size - 4],
  ]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx;
        const y = cy + dy;
        if (x < 0 || y < 0 || x >= size || y >= size) continue;
        const d = Math.max(Math.abs(dx), Math.abs(dy));
        setFixed(g, x, y, d !== 2 && d !== 4);
      }
    }
  }
  // alignment patterns, except where they would sit on a finder
  const pos = ALIGN[version - 1];
  for (const ay of pos) {
    for (const ax of pos) {
      if ((ax === 6 && ay === 6) || (ax === 6 && ay === size - 7) || (ax === size - 7 && ay === 6)) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setFixed(g, ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }
  drawFormat(g, 0); // reserve the format areas; redrawn with the chosen mask
  if (version >= 7) {
    const bits = versionBits(version);
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >> i) & 1) === 1;
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      setFixed(g, a, b, dark);
      setFixed(g, b, a, dark);
    }
  }
}

function drawFormat(g: Grid, mask: number) {
  const { size } = g;
  const bits = formatBits(mask);
  const bit = (i: number) => ((bits >> i) & 1) === 1;
  // around the top-left finder
  for (let i = 0; i <= 5; i++) setFixed(g, 8, i, bit(i));
  setFixed(g, 8, 7, bit(6));
  setFixed(g, 8, 8, bit(7));
  setFixed(g, 7, 8, bit(8));
  for (let i = 9; i < 15; i++) setFixed(g, 14 - i, 8, bit(i));
  // the copy split between the other two finders
  for (let i = 0; i < 8; i++) setFixed(g, size - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) setFixed(g, 8, size - 15 + i, bit(i));
  setFixed(g, 8, size - 8, true); // the dark module
}

function placeData(g: Grid, codewords: number[]) {
  const { size } = g;
  let i = 0;
  const total = codewords.length * 8;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5; // skip the vertical timing pattern
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        if (g.fixed[y][x]) continue;
        // remainder bits stay light
        g.dark[y][x] = i < total && ((codewords[i >> 3] >> (7 - (i & 7))) & 1) === 1;
        i++;
      }
    }
  }
}

const MASKS: ((x: number, y: number) => boolean)[] = [
  (x, y) => (x + y) % 2 === 0,
  (_x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

function applyMask(g: Grid, mask: number) {
  for (let y = 0; y < g.size; y++) for (let x = 0; x < g.size; x++) if (!g.fixed[y][x] && MASKS[mask](x, y)) g.dark[y][x] = !g.dark[y][x];
}

/** The four penalty rules of ISO/IEC 18004 section 7.8.3; the lowest score picks the mask. */
export function penalty(dark: boolean[][]): number {
  const size = dark.length;
  let score = 0;
  const lines: boolean[][] = [];
  for (let i = 0; i < size; i++) {
    lines.push(dark[i]);
    lines.push(dark.map((row) => row[i]));
  }
  const finderLike = [true, false, true, true, true, false, true];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= size; i++) {
      if (i < size && line[i] === line[i - 1]) run++;
      else {
        if (run >= 5) score += 3 + run - 5;
        run = 1;
      }
    }
    for (let i = 0; i + 7 <= size; i++) {
      if (!finderLike.every((v, k) => line[i + k] === v)) continue;
      const lightBefore = i >= 4 && [1, 2, 3, 4].every((k) => !line[i - k]);
      const lightAfter = i + 11 <= size && [7, 8, 9, 10].every((k) => !line[i + k]);
      if (lightBefore || lightAfter) score += 40;
    }
  }
  let darkCount = 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (dark[y][x]) darkCount++;
      if (x + 1 < size && y + 1 < size) {
        const c = dark[y][x];
        if (dark[y][x + 1] === c && dark[y + 1][x] === c && dark[y + 1][x + 1] === c) score += 3;
      }
    }
  }
  score += Math.floor(Math.abs((darkCount * 100) / (size * size) - 50) / 5) * 10;
  return score;
}

// ---------------------------------------------------------------- encode

/** The data codewords (byte mode, terminator, padding) for a version. */
function dataCodewords(bytes: Uint8Array, version: number, capacity: number): number[] {
  const bits: number[] = [];
  const push = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  push(0b0100, 4);
  push(bytes.length, version < 10 ? 8 : 16);
  bytes.forEach((b) => push(b, 8));
  push(0, Math.min(4, capacity * 8 - bits.length));
  while (bits.length % 8) bits.push(0);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let pad = 0xec; out.length < capacity; pad ^= 0xec ^ 0x11) out.push(pad);
  return out;
}

export interface QrCode {
  version: number;
  mask: number;
  size: number;
  /** dark[y][x], without the quiet zone. */
  dark: boolean[][];
}

/** Encode text (UTF-8) at level M in the smallest version from 1 to 10 that holds it. */
export function encodeQr(text: string): QrCode {
  const bytes = new TextEncoder().encode(text);
  for (let version = 1; version <= BLOCKS_M.length; version++) {
    const [ecc, g1, d1, g2] = BLOCKS_M[version - 1];
    const capacity = g1 * d1 + g2 * (d1 + 1);
    const headerBits = 4 + (version < 10 ? 8 : 16);
    if (headerBits + bytes.length * 8 > capacity * 8) continue;

    const data = dataCodewords(bytes, version, capacity);
    const blocks: number[][] = [];
    let offset = 0;
    for (let b = 0; b < g1 + g2; b++) {
      const len = b < g1 ? d1 : d1 + 1;
      blocks.push(data.slice(offset, offset + len));
      offset += len;
    }
    const eccBlocks = blocks.map((block) => reedSolomon(block, ecc));
    const codewords: number[] = [];
    for (let i = 0; i <= d1; i++) for (const block of blocks) if (i < block.length) codewords.push(block[i]);
    for (let i = 0; i < ecc; i++) for (const block of eccBlocks) codewords.push(block[i]);

    let best: QrCode | null = null;
    let bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const g = newGrid(version);
      drawFunctionPatterns(g, version);
      placeData(g, codewords);
      applyMask(g, mask);
      drawFormat(g, mask);
      const score = penalty(g.dark);
      if (score < bestScore) {
        bestScore = score;
        best = { version, mask, size: g.size, dark: g.dark };
      }
    }
    return best as QrCode;
  }
  throw new Error(`too long for a version 10 QR code at level M: ${bytes.length} bytes`);
}

/** One SVG path of the dark modules, offset by a quiet zone of `margin` modules. */
export function qrPath(code: QrCode, margin = 4): string {
  const parts: string[] = [];
  code.dark.forEach((row, y) =>
    row.forEach((on, x) => {
      if (on) parts.push(`M${x + margin} ${y + margin}h1v1h-1z`);
    }),
  );
  return parts.join("");
}
