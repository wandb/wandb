import * as _ from 'lodash';
import * as Run from './runs';

type GroupFilterOp = 'AND' | 'OR';

export type Filter = IndividualFilter | GroupFilter;

// needs to match IndividualFilter.op
const ops = ['=', '!=', '<', '>', '<=', '>='];
export interface IndividualFilter {
  op: '=' | '!=' | '<' | '>' | '<=' | '>=';
  key: Run.Key;
  value: Run.Value;
}

export interface GroupFilter {
  op: 'AND' | 'OR';
  filters: Filter[];
}

const filt: Filter = {
  key: {
    section: 'run',
    name: 'n',
  },
  op: '=',
  value: null,
};

function isGroup(filter: Filter): filter is GroupFilter {
  return (filter as GroupFilter).filters !== undefined;
}

export function match(filter: Filter, run: Run.Run): boolean {
  if (isGroup(filter)) {
    const result = filter.filters.map(f => match(f, run));
    if (filter.op === 'AND') {
      return result.every(o => o);
    } else {
      return result.some(o => o);
    }
  } else {
    const value = Run.getValue(run, filter.key);
    if (filter.op === '=') {
      if (filter.value === '*') {
        return value != null;
      } else {
        return filter.value === value;
      }
    } else if (filter.op === '!=') {
      if (filter.value === '*') {
        return value === null;
      }
      return filter.value !== value;
    }
    // Have to convert to IndividiualFilter here for some reason, without this
    // the compiler complains that filter.value could be null, even though we're
    // checking it.
    const ifilt = filter as IndividualFilter;
    if (ifilt.value != null && value != null) {
      if (ifilt.op === '<') {
        return ifilt.value < value;
      } else if (filter.op === '>') {
        return ifilt.value > value;
      } else if (filter.op === '<=') {
        return ifilt.value <= value;
      } else if (filter.op === '>=') {
        return ifilt.value >= value;
      }
    }
  }
  return false;
}

export function filterRuns(filter: Filter, runs: Run.Run[]) {
  return runs.filter(run => match(filter, run));
}

///// check* functions and fromJson are used for making sure server data is
// in the format we expect. We convert it to safely typed TypeScript data.

function checkIndividualFilter(filter: any) {
  // Not extremely thorough.
  if (_.indexOf(ops, filter.op) === -1) {
    return false;
  }
  if (
    typeof filter.key !== 'object' ||
    filter.key.section == null ||
    filter.key.name == null
  ) {
    return false;
  }
  if (filter.value == null) {
    return false;
  }
  return true;
}

function checkGroupFilter(filter: any): boolean {
  if (filter.op !== 'AND' && filter.op !== 'OR') {
    return false;
  }
  return checkGroupFilterSet(filter.filters);
}

function checkGroupFilterSet(filters: any): boolean {
  if (!(filters instanceof Array)) {
    return false;
  }
  for (const filter of filters) {
    if (!checkFilter(filter)) {
      return false;
    }
  }
  return true;
}

function checkFilter(filter: any): boolean {
  if (filter.op === 'AND' || filter.op === 'OR') {
    return checkGroupFilter(filter);
  } else {
    return checkIndividualFilter(filter);
  }
}

export function fromJson(json: any): Filter | null {
  if (checkGroupFilterSet(json)) {
    // This is the old format, a top-level array of individual filters to be
    // AND'd together.
    return {op: 'AND', filters: json};
  } else {
    if (checkFilter(json)) {
      return json;
    } else {
      return null;
    }
  }
}
