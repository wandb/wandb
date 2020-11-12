export function updateArrayIndex<T>(a: T[], index: number, item: T): T[] {
  return [...a.slice(0, index), item, ...a.slice(index + 1)];
}

export function deleteArrayIndex<T>(a: T[], index: number): T[] {
  return [...a.slice(0, index), ...a.slice(index + 1)];
}

export function insertArrayItem<T>(a: T[], index: number, item: T): T[] {
  return [...a.slice(0, index), item, ...a.slice(index)];
}
