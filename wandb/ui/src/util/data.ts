import * as _ from 'lodash';

// This file is meant to contain functions for working with
// javascript data structures, similar to what lodash provides.

/**
 * Deep diff between two object, using lodash
 * @param  {Object} object Object compared
 * @param  {Object} base   Object to compare with
 *
 * @return {Object}        Return a new object who represent the diff
 *
 */
export function difference<T, G>(object: T, base: G): Partial<T> | Partial<G> {
  function changes(object2: any, base2: any) {
    return _.transform(object2, (result: any, value, key) => {
      if (!_.isEqual(value, base2[key])) {
        result[key] =
          _.isObject(value) && _.isObject(base2[key])
            ? changes(value, base2[key])
            : value;
      }
    });
  }
  return changes(object, base);
}

export function randID(length: number) {
  let result = '';
  const characters =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const charactersLength = characters.length;
  for (let i = 0; i < length; i++) {
    result += characters.charAt(Math.floor(Math.random() * charactersLength));
  }
  return result;
}

/**
 * Retrieve a fixed number of elements from an array, evenly distributed but
 * always including the first and last elements.
 *
 *  n = 0 returns empty []
 *  n = 1 returns [last]
 *  n = 2 returns [first, last]
 *  n > collection.length returns [first, last]
 *
 */
export function sampleSorted<T>(collection: T[], n: number): T[] {
  if (n < 1) {
    return [];
  }
  if (n === 1) {
    return [collection[collection.length - 1]];
  }
  if (n >= collection.length) {
    return collection;
  }
  const elements = [collection[0]];
  const totalItems = collection.length - 2;
  const interval = totalItems / (n - 1);

  for (let i = 1; i < n - 1; i++) {
    elements.push(collection[Math.round(i * interval)]);
  }
  elements.push(collection[collection.length - 1]);

  return elements;
}

// Takes a range and a collection
//
// Expands the range to the closest range that captures
// a number of elements in the collection equal to size
//
// Constraints:
// The range is Inclusive
//
// Collection must be sorted
export function expandRangeToNElements(
  range: [number, number],
  collection: number[],
  n: number
): [number, number] {
  const [begin, end] = range;
  let startI: number | undefined;
  let endI: number | undefined;

  startI = _.sortedIndex(collection, begin);
  endI = _.sortedIndex(collection, end);

  const itemsInRange = endI - startI + 1;

  // Split the remaining element count in two to grab from front and back
  const itemsToFetch = Math.max(n - itemsInRange, 0);
  if (itemsInRange > n) {
    return [collection[startI], collection[endI]];
  }

  let frontHalf = Math.floor(itemsToFetch / 2);
  const backHalf = Math.ceil(itemsToFetch / 2);
  let newBeginI;
  let newEndI;

  // If there is not enough to add on behind take more in front
  if (backHalf + endI > collection.length - 1) {
    frontHalf += backHalf + endI - (collection.length - 1);
  }

  // When there is not enough items to look back start at 0
  // NOTE: The missing items will be reclaimed in the final calc
  if (startI < frontHalf) {
    newBeginI = 0;
  } else {
    newBeginI = startI - frontHalf;
  }

  newEndI = Math.min(newBeginI + n, collection.length) - 1;

  return [collection[newBeginI], collection[newEndI]];
}

// Grouped List
//
// These are useful as set of tools for dealing with grouped data
// in conjunction with singular items, a common pattern in our UI
export interface Group<T> {
  // Currently only supports grouping via multiple media keys
  groupType: 'mediaKeys';
  items: T[];
}

// A grouped list is a list of items with either a singular value or a group
export type GroupedList<T> = Array<T | Group<T>>;

export function firstGrouped<T>(list: GroupedList<T>) {
  const firstTile = _.get(list, 0, null);

  return firstTile && typeof firstTile === 'object' && 'groupType' in firstTile
    ? firstTile.items[0]
    : firstTile;
}

// Loops through all the items in the list and executes the given
// function on each item and each sub item if its a group
export function mapGroupedLeafs<T, G>(
  list: GroupedList<T>,
  f: (value: T) => G
): GroupedList<G> {
  return list.map(i => {
    if (i != null && typeof i === 'object' && 'groupType' in i) {
      return {groupType: i.groupType, items: i.items.map(f)};
    } else {
      return f(i);
    }
  });
}

interface NestedMap<T> {
  [key: string]: T | NestedMap<T>;
}

export function nestedKeyPaths<T>(
  a: NestedMap<T>,
  isLeaf?: (v: T | NestedMap<T>) => boolean
) {
  const o = [] as string[][];

  isLeaf = isLeaf ?? _.isPlainObject;

  for (const k of Object.keys(a)) {
    const v = a[k];
    if (isLeaf(v)) {
      o.push([k]);
    } else {
      nestedKeyPaths(v as any).forEach(ks => {
        o.push([k, ...ks]);
      });
    }
  }

  return o;
}

export function move<T>(array: T[], from: number, to: number) {
  if (from === to) {
    return array;
  }

  const el = array[from];
  if (to > from) {
    return [
      ...array.slice(0, from),
      ...array.slice(from + 1, to),
      el,
      ...array.slice(to),
    ];
  } else {
    return [
      ...array.slice(0, to),
      el,
      ...array.slice(to, from),
      ...array.slice(from + 1),
    ];
  }
}

export const repeatMany = (a: unknown[], n: number) =>
  Array(n)
    .fill(a)
    .flat(1);
