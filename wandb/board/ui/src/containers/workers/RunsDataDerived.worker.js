import {
  displayFilterKey,
  updateRuns,
  flatKeySuggestions,
  setupKeySuggestions,
  filterRuns,
  sortRuns,
  getColumns,
} from '../../util/runhelpers.js';
import {JSONparseNaN} from '../../util/jsonnan';
import * as Query from '../../util/query';
import _ from 'lodash';

let runs = [];

function handleMessage(m, postMessage) {
  let {base, prevRuns, query} = m.data;
  let curRuns = m.data.runs;
  if (Query.canReuseBaseData(query)) {
    runs = base;
  } else {
    runs = updateRuns(prevRuns, curRuns, []);
  }
  let filteredRuns = sortRuns(query.sort, filterRuns(query.filters, runs));
  let keySuggestions = setupKeySuggestions(runs);
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
  let data = {
    base: runs,
    filtered: filteredRuns,
    filteredRunsById,
    selectedRuns,
    selectedRunsById,
    keys: keySuggestions,
    axisOptions,
    columnNames,
  };
  postMessage(data);
}

self.addEventListener('message', m => {
  handleMessage(m, self.postMessage);
});

// This is used only in tests.
export default class FakeWorker {
  constructor(stringUrl) {
    this.url = stringUrl;
    this.onmessage = () => {};
  }

  postMessage(m) {
    // Commented out because it causes the test to crash
    //handleMessage(m, this.onmessage);
  }
}
