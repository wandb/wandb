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

export function mergeKeyVals(keyVals: Run.KeyVal[]): Run.KeyVal {
  const keys = _.uniq(_.flatMap(keyVals, (kv: Run.KeyVal) => _.keys(kv)));
  const result: {[key: string]: Run.Value | undefined} = {};
  for (const key of keys) {
    const values = keyVals.map(kv => kv[key]);
    if (typeof values[0] === 'number') {
      result[key] = _.sum(values) / values.length;
    } else {
      result[key] = values[0];
    }
  }
  return result;
}

export function mergeRunsBase(runs: Run.Run[]) {
  return {
    id: runs[0].id,
    state: runs[0].state,
    user: runs[0].user,
    host: runs[0].host,
    createdAt: runs[0].createdAt,
    heartbeatAt: runs[0].heartbeatAt,
    tags: runs[0].tags,
    description: '',
  };
}

export function mergeRuns(runs: Run.Run[], name: string): Run.Run {
  return {
    ...mergeRunsBase(runs),
    name,
    config: mergeKeyVals(runs.map(r => r.config)),
    summary: mergeKeyVals(runs.map(r => r.summary)),
  };
}

export function subgroupRuns(
  runs: Run.Run[],
  groupKey: string,
  subgroupKey: string
): Run.Run[] {
  const result: {[group: string]: {[subgroup: string]: Run.Run[]}} = {};
  for (const run of runs) {
    const group = run.config[groupKey] as string;
    const subgroup = run.config[subgroupKey] as string;
    if (group == null || subgroup == null) {
      continue;
    }
    if (result[group] == null) {
      result[group] = {};
    }
    if (result[group][subgroup] == null) {
      result[group][subgroup] = [];
    }
    result[group][subgroup].push(run);
  }
  const merged = _.mapValues(result, (group, groupName) =>
    _.map(group, (sgRuns, subgroup) => mergeRuns(sgRuns, subgroup))
  );

  return _.flatMap(merged);
}

export function pivotKeyVals(
  nameAndKeyVals: Array<[string, Run.KeyVal]>
): Run.KeyVal {
  let result: {[key: string]: Run.Value | undefined} = {};
  for (const nameKV of nameAndKeyVals) {
    const [name, kv] = nameKV;
    result = Object.assign(result, _.mapKeys(kv, (v, k) => name + '$' + k));
  }
  return result;
}

export function pivotRuns(runs: Run.Run[], name: string): Run.Run {
  const result = {
    ...mergeRunsBase(runs),
    name,
    config: pivotKeyVals(runs.map(r => {
      return [r.name, r.config];
    }) as Array<[string, Run.KeyVal]>),
    summary: pivotKeyVals(runs.map(r => {
      return [r.name, r.summary];
    }) as Array<[string, Run.KeyVal]>),
  };
  return result;
}

export function groupRuns(runs: Run.Run[], groupKey: string): Run.Run[] {
  const result: {[group: string]: Run.Run[]} = {};
  for (const run of runs) {
    const group = run.config[groupKey] as string;
    if (group == null) {
      continue;
    }
    if (result[group] == null) {
      result[group] = [];
    }
    result[group].push(run);
  }
  return _.map(result, pivotRuns);
}
