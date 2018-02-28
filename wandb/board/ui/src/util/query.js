import _ from 'lodash';
import update from 'immutability-helper';

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
    filterID = filters.length > 0 ? _.max(_.keys(filters)) + 1 : 0;
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
