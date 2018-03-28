export function parseDate(date: any): Date | null {
  if (typeof date !== 'string') {
    return null;
  }
  const dateObj = new Date(date + 'z');
  try {
    dateObj.toISOString();
  } catch {
    return null;
  }
  return dateObj;
}
