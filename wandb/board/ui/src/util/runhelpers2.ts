// Typescript runhelpers.
// TODO: rename to runhelpers once everything is moved over.

import * as _ from 'lodash';

import * as Run from './runs';

export function keySuggestions(pathCountsString: string): string[] | null {
  const json = JSON.parse(pathCountsString);
  if (!_.isObject(json)) {
    return null;
  }
  return (_.keys(json)
    .map(Run.serverPathToKeyString)
    .filter(o => o) as string[]).sort();
}
