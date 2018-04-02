/* Semantic UI helpers */

export function makeOptions(values) {
  return values.map(v => ({text: v, key: v, value: v}));
}
