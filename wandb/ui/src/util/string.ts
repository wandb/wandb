import * as _ from 'lodash';

// Splits a string on the first occurence of delim. If delim isn't present, returns [s, null]
export function splitOnce(s: string, delim: string): [string, string | null] {
  const delimLoc = _.indexOf(s, delim);
  if (delimLoc === -1) {
    return [s, null];
  }
  return [s.slice(0, delimLoc), s.slice(delimLoc + 1)];
}

export function splitOnceLast(
  s: string,
  delim: string
): [string, string] | [null, null] {
  const delimLoc = _.lastIndexOf(s, delim);
  if (delimLoc === -1) {
    return [null, null];
  }
  return [s.slice(0, delimLoc), s.slice(delimLoc + 1)];
}

export function stripQuotesAndSpace(s: any) {
  if (typeof s === 'string') {
    return s.replace(/^["\s]+|["\s]+$/g, '');
  } else {
    return s;
  }
}

export function capitalizeFirst(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function isValidEmail(s: string) {
  return /(.+)@(.+){2,}\.(.+){2,}/.test(s);
}

export function ID(length: number) {
  // Math.random should be unique because of its seeding algorithm.
  // Convert it to base 36 (numbers + letters), and grab the first 9 characters
  // after the decimal.
  return Math.random()
    .toString(36)
    .substr(2, length);
}
