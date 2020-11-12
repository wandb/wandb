declare global {
  interface String {
    padStart(length: number, char: string): string;
  }
}

export function b64ToHex(b64String: string) {
  try {
    const dig = atob(b64String);
    let result = '';
    for (const c of dig) {
      result += c
        .charCodeAt(0)
        .toString(16)
        .padStart(2, '0');
    }
    return result;
  } catch (e) {
    console.error('Unable to decode digest: ', b64String);
    return b64String;
  }
}

export function hexToId(hex: string) {
  try {
    let result = '';
    for (let i = 0; i < hex.length; i += 2) {
      result += String.fromCharCode(parseInt(hex.substr(i, 2), 16));
    }
    return btoa(result);
  } catch (e) {
    console.error('Unable to decode digest: ', hex);
    return hex;
  }
}
