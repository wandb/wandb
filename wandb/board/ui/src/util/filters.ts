import update, {Query} from 'immutability-helper';
import * as _ from 'lodash';
import * as Run from './runs';

type GroupFilterOp = 'AND' | 'OR';

export type Filter = IndividualFilter | GroupFilter;

// needs to match IndividualFilter.op
// TODO: using enum may allow us to get rid of the duplication.
const ops = ['=', '!=', '<', '>', '<=', '>='];
export type IndividiualOp = '=' | '!=' | '<' | '>' | '<=' | '>=';
export interface IndividualFilter {
  readonly op: IndividiualOp;
  readonly key: Run.Key;
  readonly value: Run.Value;
}

export interface GroupFilter {
  readonly op: 'AND' | 'OR';
  readonly filters: Filter[];
}

export function isGroup(filter: Filter): filter is GroupFilter {
  return (filter as GroupFilter).filters !== undefined;
}

export function isIndividual(filter: Filter): filter is IndividualFilter {
  return (filter as IndividualFilter).key !== undefined;
}

export function isEmpty(filter: Filter): boolean {
  return isIndividual(filter) && filter.key.name === '';
}

export function match(filter: Filter, run: Run.Run): boolean {
  if (isGroup(filter)) {
    const result = filter.filters.map(f => match(f, run));
    if (filter.op === 'AND') {
      return result.every(o => o);
    } else {
      return result.some(o => o);
    }
  } else if (isIndividual(filter)) {
    if (filter.key.name === '') {
      return true;
    }
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
        return value < ifilt.value;
      } else if (filter.op === '>') {
        return value > ifilt.value;
      } else if (filter.op === '<=') {
        return value <= ifilt.value;
      } else if (filter.op === '>=') {
        return value >= ifilt.value;
      }
    }
  }
  return false;
}

export function filterRuns(filter: Filter, runs: Run.Run[]) {
  return runs.filter(run => match(filter, run));
}

type QueryPathItem = number | string;
export class Update {
  static groupPush(path: QueryPathItem[], filter: Filter): Query<GroupFilter> {
    return genUpdate(path, {filters: {$push: [filter]}});
  }

  static groupRemove(path: QueryPathItem[], index: number): Query<GroupFilter> {
    return genUpdate(path, {filters: {$splice: [[index, 1]]}});
  }

  static setFilter(path: QueryPathItem[], filter: Filter): Query<GroupFilter> {
    return genUpdate(path, {$set: filter});
  }
}

// Can't build this up as query directly, so we take the Tree type from
// immutability-helper and use it.
type Tree<T> = {[K in keyof T]?: Query<T[K]>};
function genUpdate(path: QueryPathItem[], updateQuery: Query<any>): Query<any> {
  const result: Tree<any> = {};
  let node = result;
  path.forEach((pathItem, i) => {
    node.filters = {[pathItem]: {}};
    node = node.filters[pathItem] as Tree<any>;
  });
  Object.assign(node, updateQuery);
  return result;
}

///// check* functions and fromJson are used for making sure server data is
// in the format we expect. We convert it to safely typed TypeScript data.

function checkIndividualFilter(filter: any): IndividualFilter | null {
  if (_.indexOf(ops, filter.op) === -1) {
    return null;
  }
  let filterKey: Run.Key | null;
  // We allow both colon-separate string or object formats.
  if (typeof filter.key === 'string') {
    filterKey = Run.keyFromString(filter.key);
  } else if (typeof filter.key === 'object') {
    filterKey = Run.key(filter.key.section, filter.key.name);
  } else {
    return null;
  }
  if (filterKey == null) {
    return null;
  }
  if (filter.value == null) {
    return null;
  }
  return {
    key: filterKey,
    op: filter.op,
    value: filter.value,
  };
}

function checkGroupFilter(filter: any): GroupFilter | null {
  if (filter.op !== 'AND' && filter.op !== 'OR') {
    return null;
  }
  const filters = checkGroupFilterSet(filter.filters);
  if (!filters) {
    return null;
  }
  return {
    op: filter.op,
    filters,
  };
}

function checkGroupFilterSet(filters: any): Filter[] | null {
  if (!(filters instanceof Array)) {
    return null;
  }
  const result = filters.map(checkFilter);
  if (result.some(o => o == null)) {
    return null;
  }
  // We know none of them are null after the check above.
  return result as Filter[];
}

function checkFilter(filter: any): Filter | null {
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
    // TODO: Fix
    return {op: 'AND', filters: json};
  } else {
    return checkFilter(json);
  }
}

export function fromOldURL(filterStrings: string[]): Filter | null {
  /* Read filters from the old URL format */
  const result = filterStrings.map(filterString => {
    let parsed;
    try {
      parsed = JSON.parse(filterString);
    } catch (e) {
      return null;
    }
    if (!_.isArray(parsed) || parsed.length !== 3) {
      return null;
    }
    const [keyString, op, valueAny] = parsed;
    const value: Run.Value = valueAny;
    const key = Run.keyFromString(keyString);
    if (key == null || key.section == null || key.name == null) {
      return null;
    }
    return {key, op, value};
  });
  if (result.some(f => !f)) {
    return null;
  }
  return fromJson(result);
}

export function fromOldQuery(oldQuery: any): Filter | null {
  // Parses filters stored in the old format. Not super safe.
  if (!_.isArray(oldQuery)) {
    return null;
  }
  const individualFilters: any = oldQuery
    .map(
      (f: any) =>
        f.key && f.key.section && f.key.value && f.op && f.value
          ? {
              key: {section: f.key.section, name: f.key.value},
              op: f.op,
              value: f.value,
            }
          : null,
    )
    .filter(o => o);
  return {op: 'OR', filters: [{op: 'AND', filters: individualFilters}]};
}

export function fromURL(filterString: string): Filter | null {
  let result;
  try {
    result = JSON.parse(filterString);
  } catch {
    return null;
  }
  return fromJson(result);
}

export function toURL(filter: Filter): string {
  return JSON.stringify(filter);
}

export function countIndividual(filter: Filter): number {
  if (isIndividual(filter)) {
    return 1;
  } else if (isGroup(filter)) {
    return filter.filters.reduce((total, f) => total + countIndividual(f), 0);
  }
  return 0;
}
