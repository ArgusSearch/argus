/** Supersample the small faces and costume strokes, with a ceiling on per-frame canvas work. */
export function avatarPixelRatio(devicePixelRatio: number): number {
  return Math.min(3, Math.max(2, devicePixelRatio || 1));
}
