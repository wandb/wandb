import _ from 'lodash';

// Check if value is not empty, as type predicate.
// Especially useful for ['a', null, 'b'].filter(isEmpty).
//     returned type will be string[]
export function notEmpty<TValue>(
  value: TValue | null | undefined
): value is TValue {
  return value != null;
}

export function notArray<TValue>(
  value: TValue | TValue[] | null | undefined
): value is TValue {
  return !Array.isArray(value);
}

export interface Obj {
  [key: string]: any;
}
export function isObject(val: any): val is Obj {
  return _.isObject(val);
}

export function deepMapValuesAndArrays(obj: any, mapFn: (o: any) => any): any {
  if (_.isArray(obj)) {
    // let the caller map arrays.
    const arr = mapFn(obj);
    return arr.map((item: any) => deepMapValuesAndArrays(item, mapFn));
  }
  if (typeof obj === 'object') {
    return _.mapValues(obj, v => deepMapValuesAndArrays(v, mapFn));
  }
  return mapFn(obj);
}

type DeArray<T> = T extends Array<infer E> ? E : never;
type Pivot<T extends any[][]> = Array<{[key in keyof T]: DeArray<T[key]>}>;
export function zip<T extends any[][]>(...args: T): Pivot<T> {
  return _.zip(...args) as Pivot<T>;
}

export function shallowEqual<TValue>(a: TValue, b: TValue): boolean {
  if ((a == null) !== (b == null)) {
    return false;
  }

  for (const key in a) {
    if (!(key in b) || a[key] !== b[key]) {
      return false;
    }
  }

  for (const key in b) {
    if (!(key in a) || a[key] !== b[key]) {
      return false;
    }
  }

  return true;
}

export function toIncludesObj(list: string[]): {[key: string]: true} {
  const includesObj: {[key: string]: true} = {};
  list.forEach(x => (includesObj[x] = true));
  return includesObj;
}
