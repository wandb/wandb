import _ from 'lodash';
import update from 'immutability-helper';
import * as Run from './runs';
import * as Filter from './filters';

export function merge(base, apply) {
  let result = {};
  result.page = apply.page;
  result.entity = apply.entity || base.entity;
  // Use model as well for old data.
  result.project = apply.project || apply.model || base.project;

  // AND the two sets of filters together
  if (apply.filters) {
    let applyFilters = apply.filters;
    if (_.isObject(apply.filters) && apply.filters.op == null) {
      // Handle the old format
      applyFilters = Filter.fromOldQuery(_.values(apply.filters));
    }
    result.filters = {op: 'AND', filters: [base.filters, applyFilters]};
  } else {
    result.filters = base.filters;
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
  if (query.filters == null) {
    return null;
  }
  let filters = query.filters;
  if (filters.op == null) {
    filters = Filter.fromOldQuery(_.values(query.filters));
  }
  if (filters == null) {
    return null;
  }
  return Filter.summaryString(filters);
}

export function project(query) {
  return query && (query.project || query.model);
}
