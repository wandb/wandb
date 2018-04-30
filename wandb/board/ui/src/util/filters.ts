import update, {Query} from 'immutability-helper';
import * as _ from 'lodash';
import * as Run from './runs';

type GroupFilterOp = 'AND' | 'OR';

export type Filter = IndividualFilter | GroupFilter;

// needs to match IndividualFilter.op
// TODO: using enum may allow us to get rid of the duplication.
const valueOps = ['=', '!=', '<', '>', '<=', '>='];
export type ValueOp = '=' | '!=' | '<' | '>' | '<=' | '>=';
export interface ValueFilter {
  readonly op: ValueOp;
  readonly key: Run.Key;
  readonly value: Run.Value;
}

const multiValueOps = ['IN'];
export type MultiValueOp = 'IN';
export interface MultiValueFilter {
  readonly op: MultiValueOp;
  readonly key: Run.Key;
  readonly value: Run.Value[];
}

const ops = valueOps.concat(multiValueOps);
export type IndividualOp = ValueOp | MultiValueOp;
export type IndividualFilter = ValueFilter | MultiValueFilter;

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

export function isMultiValue(
  filter: IndividualFilter
): filter is MultiValueFilter {
  return isMultiOp(filter.op);
}

export function isMultiOp(op: IndividualOp): op is MultiValueOp {
  return _.indexOf(multiValueOps, op) !== -1;
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
    if (filter.value != null && value != null) {
      if (filter.op === '<') {
        return value < filter.value!;
      } else if (filter.op === '>') {
        return value > filter.value!;
      } else if (filter.op === '<=') {
        return value <= filter.value!;
      } else if (filter.op === '>=') {
        return value >= filter.value!;
      } else if (isMultiValue(filter)) {
        return _.indexOf(filter.value, value) !== -1;
      }
    }
  }
  return false;
}

export function filterRuns(filter: Filter, runs: Run.Run[]) {
  return runs.filter(run => match(filter, run));
}

export function And(filters: Filter[]): Filter {
  return {op: 'AND', filters};
}

type QueryPathItem = number | string;
export class Update {
  static groupPush<T>(owner: T, path: QueryPathItem[], filter: Filter): T {
    return update(owner, genUpdate(path, {filters: {$push: [filter]}}));
  }

  static groupRemove<T>(owner: T, path: QueryPathItem[], index: number): T {
    return update(owner, genUpdate(path, {filters: {$splice: [[index, 1]]}}));
  }

  static setFilter<T>(owner: T, path: QueryPathItem[], filter: Filter): T {
    return update(owner, genUpdate(path, {$set: filter}));
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
  if (isMultiValue(filter)) {
    return {
      key: filterKey,
      op: filter.op,
      value: filter.value,
    };
  } else {
    return {
      key: filterKey,
      op: filter.op,
      value: Run.parseValue(filter.value),
    };
  }
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
  return checkFilter(json);
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
  if (result.some(f => f == null)) {
    return null;
  }
  const andFilters = checkGroupFilterSet(result);
  if (andFilters == null) {
    return null;
  }
  return {op: 'OR', filters: [{op: 'AND', filters: andFilters}]};
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
          : null
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

export function flatIndividuals(filter: Filter): IndividualFilter[] {
  if (isIndividual(filter)) {
    return [filter];
  } else if (isGroup(filter)) {
    return filter.filters.reduce(
      (acc, f) => acc.concat(flatIndividuals(f)),
      [] as IndividualFilter[]
    );
  }
  return [];
}

export function countIndividual(filter: Filter): number {
  return flatIndividuals(filter).length;
}

export function displayIndividualValue(filter: IndividualFilter): string {
  let value: string = '';
  if (isMultiValue(filter)) {
    if (filter.value != null) {
      value = filter.value.join(',');
    } else {
      value = 'null;';
    }
  } else {
    value = Run.displayValue(filter.value);
  }
  return value;
}

function displayIndividual(filter: IndividualFilter): string {
  return (
    Run.displayKey(filter.key) +
    ' ' +
    filter.op +
    ' ' +
    displayIndividualValue(filter)
  );
}

export function summaryString(filter: Filter): string {
  // This just finds all individual filters in the tree and displays
  // them as a comma-separated list. Obviously not fully descriptive,
  // but works for the common case where we have a single AND within
  // an OR
  const filts = flatIndividuals(filter);
  return _.map(filts, displayIndividual).join(', ');
}

export function domValue(
  filter: IndividualFilter
): Run.DomValue | Run.DomValue[] {
  if (isMultiValue(filter)) {
    if (filter.value == null) {
      return [];
    } else {
      return filter.value.map(Run.domValue);
    }
  } else {
    return Run.domValue(filter.value);
  }
}

export function simplify(filter: Filter): Filter | null {
  // Removes any group filters that are empty. Could become more advanced, for
  // example converting ORs with the same key (at the same level) to IN.
  if (isGroup(filter)) {
    const newFilter = {
      ...filter,
      filters: filter.filters.map(simplify).filter(o => o) as Filter[],
    };
    if (newFilter.filters.length === 0) {
      return null;
    }
    return newFilter;
  }
  return filter;
}

const INDIVIDUAL_OP_TO_MONGO = {
  '!=': '$ne',
  '>': '$gt',
  '>=': '$gte',
  '<': '$lt',
  '<=': '$lte',
  IN: '$in',
};
function toMongoOpValue(op: IndividualOp, value: Run.Value | Run.Value[]): any {
  if (op === '=') {
    return value;
  } else {
    return {[INDIVIDUAL_OP_TO_MONGO[op]]: value};
  }
}

function toMongoIndividual(filter: IndividualFilter): any {
  if (filter.key.name === '') {
    return null;
  }
  if (filter.key.section === 'tags') {
    if (filter.value === false) {
      return {
        $or: [{tags: null}, {tags: {$ne: filter.key.name}}],
      };
    } else {
      return {tags: filter.key.name};
    }
  }
  const path = Run.keyToServerPath(filter.key);
  if (path == null) {
    return path;
  }
  return {
    [path]: toMongoOpValue(filter.op, filter.value),
  };
}

const GROUP_OP_TO_MONGO = {
  AND: '$and',
  OR: '$or',
};
export function toMongo(filter: Filter): any {
  if (isIndividual(filter)) {
    return toMongoIndividual(filter);
  } else if (isGroup(filter)) {
    return {
      [GROUP_OP_TO_MONGO[filter.op]]: filter.filters
        .map(toMongo)
        .filter(o => o),
    };
  }
}
