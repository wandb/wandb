import * as Run from './runs';

// type FilterOp = '=' | '!=' | '<' | '>' | '<=' | '>=';

// // filter has a filter method, which takes a list of runs and returns runs
// interface Filter {
//   match(run: Run.Run): boolean;
// }

// export class IndividualFilter {
//   constructor(
//     public key: Run.Key,
//     public op: FilterOp,
//     public value: Run.Value,
//   ) {
//     this.match = this.match.bind(this);
//   }

//   match(run: Run.Run): boolean {
//     const value = Run.getValue(run, this.key);
//     if (this.op === '=') {
//       if (this.value === '*') {
//         return value != null;
//       } else {
//         return this.value === value;
//       }
//     } else if (this.op === '!=') {
//       if (this.value === '*') {
//         return value === null;
//       }
//       return this.value !== value;
//     }
//     if (this.value && value != null) {
//       if (this.op === '<') {
//         return this.value < value;
//       } else if (this.op === '>') {
//         return this.value > value;
//       } else if (this.op === '<=') {
//         return this.value <= value;
//       } else if (this.op === '>=') {
//         return this.value >= value;
//       }
//     }

//     return false;
//   }
// }

type GroupFilterOp = 'AND' | 'OR';

export type Filter = IndividualFilter | GroupFilter;

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
