// Typescript runhelpers.
// TODO: rename to runhelpers once everything is moved over.

import * as _ from 'lodash';

import * as Run from './runs';

export function keySuggestions(
  pathCountsString: string,
  minCount: number
): string[] | null {
  const json = JSON.parse(pathCountsString);
  if (!_.isObject(json)) {
    return null;
  }
  const validCountKeys = _.map(
    json,
    (count, key) => (count >= minCount ? key : null)
  ).filter(o => o != null) as string[];
  return ['name'].concat(
    (validCountKeys
      .map(Run.serverPathToKeyString)
      .filter(o => o) as string[]).sort()
  );
}
