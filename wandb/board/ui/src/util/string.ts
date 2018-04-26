import * as _ from 'lodash';

export function splitOnce(
  s: string,
  delim: string
): [string, string] | [null, null] {
  const delimLoc = _.indexOf(s, delim);
  if (delimLoc === -1) {
    return [null, null];
  }
  return [s.slice(0, delimLoc), s.slice(delimLoc + 1)];
}
