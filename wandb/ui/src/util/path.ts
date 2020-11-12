export function baseName(path: string) {
  const parts = path.split('/');
  return parts[parts.length - 1];
}

export function extension(path: string) {
  const name = baseName(path);
  const parts = name.split('.');
  return parts[parts.length - 1];
}
