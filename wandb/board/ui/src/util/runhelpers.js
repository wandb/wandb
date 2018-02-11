import _ from 'lodash';
import numeral from 'numeral';

export function convertValue(string) {
  let val = Number.parseFloat(string);
  return Number.isNaN(val) ? string : val;
}

// Takes a value (summary value or config value) and makes it into something
// we can display in html.
export function displayValue(value) {
  if (_.isNull(value) || _.isUndefined(value)) {
    return '-';
  } else if (typeof value === 'number') {
    if (_.isFinite(value)) {
      return numeral(value).format('0.[000]');
    } else {
      return value.toString();
    }
  } else {
    return JSON.stringify(value);
  }
}

// Takes a value and returns something that we can sort on and compare. Used
// by run filters.
export function sortableValue(value) {
  if (typeof value === 'number' || typeof value === 'string') {
    return value;
  } else {
    return JSON.stringify(value);
  }
}

export function runFilterCompare(op, argValue, value) {
  if (op === '=') {
    if (argValue === '*') {
      return !_.isNil(value);
    } else {
      return argValue === value;
    }
  } else if (op === '!=') {
    return argValue !== value;
  } else if (op === '<') {
    return value < argValue;
  } else if (op === '>') {
    return value > argValue;
  } else if (op === '<=') {
    return value <= argValue;
  } else if (op === '>=') {
    return value >= argValue;
  }
}

export function _getRunValueFromSectionName(run, section, name) {
  if (section === 'run') {
    if (name === 'id') {
      // Alias 'id' to 'name'.
      return run.name;
    } else {
      return run[name];
    }
  } else if (run[section]) {
    return run[section][name];
  }
  return null;
}

export function getRunValueFromFilterKey(run, filterKey) {
  return _getRunValueFromSectionName(run, filterKey.section, filterKey.value);
}

export function getRunValue(run, key) {
  let [section, name] = key.split(':', 2);
  if (name) {
    return _getRunValueFromSectionName(run, section, name);
  } else {
    return run[key];
  }
}

export function displayFilterKey(filterKey) {
  return filterKey.section + ':' + filterKey.value;
}

export function filterKeyFromString(s) {
  let [section, name] = s.split(':', 2);
  return {section: section, value: name};
}

export function filterToString(filter) {
  return JSON.stringify([
    displayFilterKey(filter.key),
    filter.op,
    filter.value,
  ]);
}

export function filterFromString(s) {
  let parsed;
  try {
    parsed = JSON.parse(s);
  } catch (e) {
    return null;
  }
  if (!_.isArray(parsed) || parsed.length !== 3) {
    return null;
  }
  let [fullKey, op, value] = parsed;
  let key = filterKeyFromString(fullKey);
  if (_.isEmpty(key.section) || _.isEmpty(key.value)) {
    return null;
  }
  return {key, op, value};
}

export function filtersForAxis(filters, axis) {
  let selections = _.values(filters);
  let sels = selections.filter(sel => displayFilterKey(sel.key) === axis);
  function getValueForOp(selections, op) {
    let opSel = _.find(selections, sel => sel.op == op);
    if (opSel) {
      return opSel.value;
    }
    return null;
  }
  return {low: getValueForOp(sels, '>'), high: getValueForOp(sels, '<')};
}

export function filterRuns(filters, runs) {
  for (var filterID of _.keys(filters)) {
    let filter = filters[filterID];
    runs = runs.filter(run =>
      runFilterCompare(
        filter.op,
        filter.value,
        sortableValue(getRunValueFromFilterKey(run, filter.key)),
      ),
    );
  }
  return runs;
}
export function sortRuns(sort, runs) {
  if (!sort.name) {
    return runs;
  }
  let getVal = run => {
    if (sort.name == 'Ran') {
      return run.createdAt;
    } else if (sort.name == 'Description') {
      return runDisplayName(run);
    } else if (sort.name == 'Runtime') {
      return (
        run.heartbeatAt && new Date(run.heartbeatAt) - new Date(run.createdAt)
      );
    } else if (sort.name == 'Stop') {
      return run.shouldStop || 0;
    } else {
      return getRunValue(run, sort.name);
    }
  };
  let cmp = (a, b) => {
    let valA = getVal(a);
    let valB = getVal(b);
    if (valA == valB) {
      return 0;
    }
    if (valA == null) {
      return 1;
    } else if (valB == null) {
      return -1;
    }
    if (sort.ascending) {
      return valA > valB ? -1 : 1;
    } else {
      return valA < valB ? -1 : 1;
    }
  };
  return runs.sort(cmp);
}

export function runDisplayName(run) {
  if (!run) {
    return '';
  }
  if (run.description) {
    return run.description.split('\n')[0];
  }
  return run.name || '';
}
