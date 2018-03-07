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
    filterID = keys.length > 0 ? _.max(keys) + 1 : 0;
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
  let strategy = apply.strategy || 'page';
  if (strategy === 'page') {
    return {...base, strategy: apply.strategy};
  }
  let result = {};
  result.strategy = apply.strategy;
  result.entity = apply.entity || base.entity;
  result.model = apply.model || base.model;

  // base and apply may share keys, so we rekey
  result.filters = {};
  let filterIndex = 0;
  for (var key of _.keys(base.filters)) {
    result.filters[filterIndex] = base.filters[key];
    filterIndex++;
  }
  for (var key of _.keys(apply.filters)) {
    result.filters[filterIndex] = apply.filters[key];
    filterIndex++;
  }

  // TODO: probably not the right thing to do
  result.selections = {...base.selections};

  result.sort = apply.sort || base.sort;
  result.num_histories = apply.num_histories || base.num_histories;
  return result;
}

export function summaryString(query) {
  if (
    !query ||
    query.strategy === 'page' ||
    _.keys(query.filters).length === 0
  ) {
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
