// Typescript runhelpers. TODO: rename to runhelpers once everything is moved
// over.
//
// TODO: tests

import * as _ from 'lodash';

import * as Run from './runs';

interface ValueCount {
  value: Run.Value;
  count: number;
}

export interface KeyValueCount {
  [key: string]: ValueCount[];
}

export function keyValueCounts(runs: Run.Run[], keys: string[]): KeyValueCount {
  const result: {[key: string]: {[value: string]: ValueCount}} = {};
  for (const keyString of keys) {
    result[keyString] = {};
    const keyResult = result[keyString];
    for (const run of runs) {
      const key = Run.keyFromString(keyString);
      if (key == null) {
        continue;
      }
      const value = Run.getValue(run, key);
      const valueString = Run.valueString(value);
      if (!keyResult[valueString]) {
        keyResult[valueString] = {value, count: 0};
      }
      keyResult[valueString].count++;
    }
  }
  return _.mapValues(result, valCounts =>
    _.sortBy(_.map(valCounts, val => val).filter(val => !_.isNil(val.value)), [
      'value',
    ]),
  );
}
