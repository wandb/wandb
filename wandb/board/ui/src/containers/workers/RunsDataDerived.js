import {
  displayFilterKey,
  updateRuns,
  setupKeySuggestions,
  filterRuns,
  sortRuns,
  getColumns,
} from '../../util/runhelpers.js';
import {JSONparseNaN} from '../../util/jsonnan';
import * as Query from '../../util/query';
import _ from 'lodash';

let runs = [];

onmessage = function(m) {
  let {base, prevBuckets, buckets, query} = m.data;
  if (Query.canReuseBaseData(query)) {
    runs = base;
  } else {
    runs = updateRuns(prevBuckets, buckets, runs);
  }
  let keySuggestions = setupKeySuggestions(runs);
  let filteredRuns = sortRuns(query.sort, filterRuns(query.filters, runs));
  let filteredRunsById = {};
  for (var run of filteredRuns) {
    filteredRunsById[run.name] = run;
  }
  let selectedRuns = [];
  if (_.size(query.selections) !== 0) {
    selectedRuns = filterRuns(query.selections, filteredRuns);
  }
  let selectedRunsById = _.fromPairs(
    selectedRuns.map(run => [run.name, run.id]),
  );

  let keys = _.flatMap(keySuggestions, section => section.suggestions);
  let axisOptions = keys.map(key => {
    let displayKey = displayFilterKey(key);
    return {
      key: displayKey,
      value: displayKey,
      text: displayKey,
    };
  });

  let columnNames = getColumns(runs);
  postMessage({
    base: runs,
    filtered: filteredRuns,
    filteredRunsById: filteredRunsById,
    selectedRuns: selectedRuns,
    selectedRunsById: selectedRunsById,
    keys: keySuggestions,
    axisOptions: axisOptions,
    columnNames: columnNames,
  });
};
