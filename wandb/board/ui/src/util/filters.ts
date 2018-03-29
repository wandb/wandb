import {Run, RunKey, RunValue} from './runs';

type FilterOp = '=' | '!=' | '<' | '>' | '<=' | '>=';

// filter has a filter method, which takes a list of runs and returns runs
interface Filter {
  match(run: Run): boolean;
}

export class IndividualFilter {
  constructor(public key: RunKey, public op: FilterOp, public value: RunValue) {
    this.match = this.match.bind(this);
  }

  match(run: Run): boolean {
    const value = run.getValue(this.key);
    if (this.op === '=') {
      if (this.value === '*') {
        return value != null;
      } else {
        return this.value === value;
      }
    } else if (this.op === '!=') {
      if (this.value === '*') {
        return value === null;
      }
      return this.value !== value;
    }
    if (this.value && value != null) {
      if (this.op === '<') {
        return this.value < value;
      } else if (this.op === '>') {
        return this.value > value;
      } else if (this.op === '<=') {
        return this.value <= value;
      } else if (this.op === '>=') {
        return this.value >= value;
      }
    }

    return false;
  }
}

type GroupFilterOp = 'AND' | 'OR';

export class GroupFilter {
  constructor(public op: GroupFilterOp, public filters: Filter[]) {
    this.match = this.match.bind(this);
  }

  match(run: Run): boolean {
    const result = this.filters.map(filter => filter.match(run));
    if (this.op === 'AND') {
      return result.every(o => o);
    } else {
      return result.some(o => o);
    }
  }
}

export function filterRuns(filter: Filter, runs: Run[]) {
  return runs.filter(filter.match);
}
