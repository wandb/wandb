export function JSONize(str: string): string {
  const segments = getStringSegments(str);

  for (let i = 0; i < segments.length; i++) {
    if (i % 2 !== 0) {
      // string segment
      continue;
    }

    // wrap keys without quote with valid double quote
    segments[i] = segments[i].replace(/([$\w]+)\s*:/g, (m, $1) => `"${$1}":`);

    // kill trailing commas
    segments[i] = segments[i].replace(/,\s*([}\]])/g, (m, $1) => $1);
  }

  return segments.join('');
}

// splits `str` into alternating JS-string/non-JS-string segments
// example:
// getStringSegments(`{asdf: "i'm ded"}`) => [`{asdf: `, `"i'm ded"`, `}`]
function getStringSegments(str: string): string[] {
  const segments: string[] = [];
  let segment = '';
  let backslash = false;
  let stringChar: string | null = null;

  for (const c of str) {
    if (stringChar == null) {
      switch (c) {
        case "'":
        case '"':
          stringChar = c;
          segments.push(segment);
          segment = '"';
          continue;
      }
    } else {
      switch (c) {
        case '\\':
          backslash = !backslash;
          break;
        case stringChar:
          if (!backslash) {
            stringChar = null;
            segments.push(segment + '"');
            segment = '';
            continue;
          }
          backslash = false;
          break;
        default:
          backslash = false;
      }
    }

    segment += c;
  }

  segments.push(segment);

  if (segments.length % 2 === 0) {
    err(`unterminated string`);
  }

  return segments;
}

function err(msg: string): never {
  throw new Error(`invalid JSON: ${msg}`);
}
