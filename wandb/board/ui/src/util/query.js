import _ from 'lodash';
import update from 'immutability-helper';
import {displayFilterKey, displayValue} from './runhelpers';

export function addFilter(filters, key, op, value) {
  let filter = _.find(
    filters,
    filter =>
      filter.key.section === key.section &&
      filter.key.value === key.value &&
      filter.op === op,
  );
  if (value === null) {
    // Remove filter if value is null
    if (!filter) {
      return filters;
    } else {
      return update(filters, {$unset: [filter.id]});
    }
  }
  let filterID;
  if (filter) {
    filterID = filter.id;
  } else {
    let keys = _.keys(filters);
    filterID = keys.length > 0 ? _.max(keys.map(Number)) + 1 : 0;
  }
  return update(filters, {
    [filterID]: {
      $set: {
        id: filterID,
        key: key,
        op: op,
        value: value,
      },
    },
  });
}

export function deleteFilter(filters, id) {
  return update(filters, {$unset: [id]});
}

export function setFilterComponent(filters, id, component, value) {
  return update(filters, {[id]: {[component]: {$set: value}}});
}

export function merge(base, apply) {
  let strat = strategy(apply);
  if (strat === 'page') {
    return {...base, strategy: apply.strategy};
  }
  let result = {};
  result.strategy = apply.strategy;
  result.entity = apply.entity || base.entity;
  result.model = apply.model || base.model;

  // base and apply may share keys, so we rekey.
  // RunFilters needs to be able to remove individual
  // filters (to compute keyValCounts) for the filters that
  // it's managing, so it's important to leave the keys alone
  // for the apply.filters.
  result.filters = {};
  for (var key of _.keys(base.filters)) {
    result.filters['base' + key] = base.filters[key];
  }
  for (var key of _.keys(apply.filters)) {
    result.filters[key] = apply.filters[key];
  }

  // TODO: probably not the right thing to do
  result.selections = {...base.selections};

  result.sort = apply.sort || base.sort;
  result.num_histories = apply.num_histories || base.num_histories;

  result.baseQuery = base;
  result.applyQuery = apply;

  return result;
}

export function summaryString(query) {
  if (strategy(query) === 'page' || _.keys(query.filters).length === 0) {
    return '';
  }
  let filtStrs = _.map(
    query.filters,
    filt =>
      displayFilterKey(filt.key) +
      ' ' +
      filt.op +
      ' ' +
      displayValue(filt.value),
  );
  return filtStrs.join(', ');
}

export function strategy(query) {
  if (!query || !query.strategy) {
    // page is the default when not explicity provided
    return 'page';
  }
  return query.strategy;
}

///// Control Flow stuff:
// The logic in these functions is kind of gnarly because we're conflating
// a few concepts with query.
// TODO: rework.

export function sameModel(q1, q2) {
  return q1.entity === q2.entity && q1.model === q2.model;
}

export function canReuseBaseData(query) {
  return strategy(query) === 'merge' && sameModel(query, query.baseQuery);
}

export function shouldPoll(query) {
  return strategy(query) === 'merge' && !sameModel(query, query.baseQuery);
}

export function needsOwnRunsQuery(query) {
  return (
    strategy(query) === 'root' ||
    (strategy(query) === 'merge' && !sameModel(query, query.baseQuery))
  );
}

export function needsOwnHistoryQuery(query) {
  return strategy(query) === 'root' || strategy(query) === 'merge';
}
///// End control flow stuff
