import React from 'react';

import _ from 'lodash';
import numeral from 'numeral';
import {JSONparseNaN} from '../util/jsonnan';
import flatten from 'flat';
import {fragments} from '../graphql/runs';
import TimeAgo from 'react-timeago';
import {Icon} from 'semantic-ui-react';
import * as Run from './runs';
import * as Filters from './filters';

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
  } else if (_.isString(value)) {
    return value;
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

// Truncate string.  Doesn't seem like there's an easy way to do this by pixel length.
// Splits the string in the middle.
export function truncateString(string, maxLength = 30) {
  if (string.length < maxLength) {
    return string;
  }
  let rightLength = Math.floor(maxLength / 2) - 1;
  let leftLength = maxLength - rightLength - 1;
  let leftSide = string.substr(0, leftLength);
  let rightSide = string.substr(-rightLength);
  let truncString = leftSide + '…' + rightSide;
  return truncString;
}

// fuzzyMatch replicates the command-P in vscode matching all the characters in order'
// but not necessarily sequential
export function fuzzyMatch(strings, matchStr) {
  if (!matchStr) {
    return strings;
  }
  var regexpStr = '';
  for (var i = 0; i < matchStr.length; i++) {
    regexpStr += matchStr.charAt(i);
    regexpStr += '.*';
  }
  var regexp = new RegExp(regexpStr, 'i');
  return strings.filter(str => str.match(regexp));
}

// fuzzyMatchHighlight works with fuzzyMatch to highlight the matching substrings
export function fuzzyMatchHighlight(
  str,
  matchStr,
  matchStyle = {backgroundColor: 'yellow'},
) {
  if (!matchStr) {
    return str;
  }
  var regexpStr = '';
  var matchStrIndex = 0;
  var matchStrArr = [...matchStr];

  return (
    <span>
      {[...str].map(
        (c, j) =>
          c == matchStrArr[matchStrIndex] ? (
            ((matchStrIndex += 1),
            (
              <span key={'span' + j + ',' + matchStrIndex} style={matchStyle}>
                {c.toString()}
              </span>
            ))
          ) : (
            <span key={'span' + j}>{c.toString()}</span>
          ),
      )}
    </span>
  );
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
    } else if (name === 'name') {
      return runDisplayName(run);
    } else if (name === 'userName') {
      return run.user.username;
    } else {
      return run[name];
    }
  } else if (section === 'tags') {
    return _.indexOf(run.tags, name) !== -1;
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
  if (!name) {
    // No colon to split on, so run section is implied.
    name = key;
    section = 'run';
  }
  return _getRunValueFromSectionName(run, section, name);
}

export function displayFilterKey(filterKey) {
  if (filterKey.section && filterKey.value) {
    if (filterKey.section === 'run') {
      return filterKey.value;
    } else {
      return filterKey.section + ':' + filterKey.value;
    }
  } else {
    return null;
  }
}

export function filterKeyFromString(s) {
  let [section, name] = s.split(':', 2);
  if (_.isNil(name)) {
    return {section: 'run', value: section};
  }
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
    let opSel = _.find(selections, sel => sel.op === op);
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
    if (!filter.key.section) {
      continue;
    }
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
    if (sort.name === 'Ran') {
      return run.createdAt;
    } else if (sort.name === 'Description') {
      return runDisplayName(run);
    } else if (sort.name === 'Runtime') {
      return (
        (run.heartbeatAt &&
          new Date(run.heartbeatAt) - new Date(run.createdAt)) ||
        0
      );
    } else if (sort.name === 'Stop') {
      return run.shouldStop || 0;
    } else {
      return getRunValue(run, sort.name);
    }
  };
  let cmp = (a, b) => {
    let valA = getVal(a);
    let valB = getVal(b);
    if (valA === valB) {
      return 0;
    }
    if (valA == null) {
      return 1;
    } else if (valB == null) {
      return -1;
    }
    if (sort.ascending) {
      return valA < valB ? -1 : 1;
    } else {
      return valA > valB ? -1 : 1;
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

export function stateToIcon(state, key) {
  let icon = 'check',
    color = 'green';
  if (state === 'failed' || state === 'crashed') {
    icon = 'remove';
    color = 'red';
  } else if (state === 'killed') {
    icon = 'remove user';
    color = 'orange';
  } else if (state === 'running') {
    icon = 'spinner';
    color = 'blue';
  }
  return (
    <Icon key={key} name={icon} color={color} loading={state === 'running'} />
  );
}

export class RunFancyName {
  constructor(run, spec) {
    this._run = run;
    this._spec = spec;
  }

  special = {
    createdAt: value => (
      <span key="createdAt">
        (started <TimeAgo date={value} />){' '}
      </span>
    ),
    stateIcon: () => stateToIcon(this._run.state, 'stateIcon'),
    runningIcon: () =>
      this._run.state === 'running'
        ? stateToIcon(this._run.state, 'runningIcon')
        : null,
  };

  toComponent() {
    if (!this._spec) {
      return runDisplayName(this._run);
    }
    return (
      <span>
        {this._spec
          .map(key => {
            let value = getRunValue(this._run, key);
            let specialFn = this.special[key];
            if (specialFn) {
              return specialFn(value);
            } else {
              if (_.isString(value)) {
                value = truncateString(value, 24);
              }
              return <span key={key}>{displayValue(value)} </span>;
            }
          })
          .filter(o => o)}
      </span>
    );
  }

  toString() {
    return this._spec
      .map(key => (this.special[key] ? null : getRunValue(this._run, key)))
      .filter(o => o)
      .map(val => displayValue(val))
      .join(' ');
  }
}

export function defaultViews(run) {
  //TODO: do we need to handle this case?
  if (!run) run = {summaryMetrics: '{}'};
  const scalars = Object.keys(JSONparseNaN(run.summaryMetrics));
  let lossy = scalars.find(s => s.match(/loss/));
  if (!lossy) {
    lossy = scalars[0];
  }
  const base = {
    runs: {
      configured: true,
      views: {
        '0': {
          defaults: [],
          name: 'Charts',
          config: [
            {
              layout: {
                x: 0,
                y: 0,
                w: 12,
                h: 2,
              },
              config: {
                source: 'history',
                key: lossy,
              },
            },
          ],
        },
      },
      tabs: [0],
    },
    run: {
      views: {
        '0': {
          defaults: [],
          name: 'Charts',
          config: [
            {
              layout: {
                x: 0,
                y: 0,
                w: 12,
                h: 2,
              },
              config: {},
            },
          ],
        },
      },
      tabs: [0],
    },
    dashboards: {
      views: {
        '0': {
          defaults: [],
          name: 'Dashboard',
          config: [
            {
              layout: {
                x: 0,
                y: 0,
                w: 12,
                h: 2,
              },
              config: {},
              query: {strategy: 'merge'},
            },
          ],
        },
      },
      tabs: [0],
    },
  };
  if (run.events && run.events.length > 0) {
    const event = JSONparseNaN(run.events[0]);
    base.run.configured = true;
    base.run.views['system'] = {
      name: 'System Metrics',
      defaults: [],
      config: [
        {
          layout: {
            x: 0,
            y: 0,
            w: 12,
            h: 2,
          },
          config: {
            source: 'events',
            lines: ['system.cpu', 'system.disk', 'system.memory'],
          },
        },
      ],
    };
    if (Object.keys(event).indexOf('system.gpu.0.gpu') > -1) {
      base.run.views.system.config.push({
        layout: {
          x: 6,
          y: 0,
          w: 6,
          h: 2,
        },
        config: {
          source: 'events',
          lines: Object.keys(event).filter(k => k.match(/system\.gpu/)),
        },
      });
      base.run.views.system.config[0].layout.w = 6;
    }
    base.run.tabs.push('system');
  }
  if (run.history && run.history.length > 0) {
    const history = JSONparseNaN(run.history[0]);
    base.run.configured = true;
    //TODO: support multi media
    if (history._media && history._media[0]._type === 'images') {
      base.run.views['images'] = {
        name: 'Images',
        defaults: [],
        config: [
          {
            layout: {
              x: 0,
              y: 0,
              w: 12,
              h: 2,
            },
            viewType: 'Images',
          },
        ],
      };
      base.run.tabs.push('images');
    }
  }
  return base;
}

// Generates relay compatible bucket id
export function relayBucketId(params) {
  return btoa(
    ['BucketType', 'v1', params.run, params.model, params.entity].join(':'),
  );
}

export function pusherProjectSlug(params) {
  return `${params.entity}@${params.model}`;
}

// Generates pusher identifier for logs
export function pusherRunSlug(params) {
  return `${pusherProjectSlug(params)}.${params.run}`;
}

export function bucketFromCache(params, client) {
  return client.readFragment({
    id: relayBucketId(params),
    fragment: fragments.basicRun,
  });
}

// Given a set of bucket edges (as returned by graphql), compute runs,
// which have the bucket JSON data parsed and flattened.
// This expects the previous version of buckets, and the previous
// result that updateRuns returned. It re-uses parsed data from the
// previous result for buckets that have not changed.
export function updateRuns(oldBuckets, newBuckets, prevResult) {
  if (!newBuckets) {
    return [];
  }
  oldBuckets = oldBuckets || {edges: []};
  let oldBucketsMap = _.fromPairs(
    oldBuckets.edges.map(edge => [edge.node.name, edge.node]),
  );
  let prevResultMap = _.fromPairs(prevResult.map(row => [row.name, row]));
  return newBuckets.edges
    .map(edge => {
      let node = edge.node;
      let run = prevResultMap[node.name];
      if (!run || node !== oldBucketsMap[node.name]) {
        run = Run.fromJson(edge.node);
      }
      return run;
    })
    .filter(o => o);
}

export function setupKeySuggestions(runs) {
  if (runs.length === 0) {
    return [];
  }

  let getSectionSuggestions = section => {
    let suggestions = _.uniq(_.flatMap(runs, run => _.keys(run[section])));
    suggestions.sort();
    return suggestions;
  };
  let runSuggestions = ['state', 'id', 'name', 'createdAt'];
  let keySuggestions = [
    {
      title: 'run',
      suggestions: runSuggestions.map(suggestion => ({
        section: 'run',
        value: suggestion,
      })),
    },
    {
      title: 'tags',
      suggestions: _.uniq(_.flatMap(runs, run => run.tags))
        .sort()
        .map(tag => ({
          section: 'tags',
          value: tag,
        })),
    },
    {
      title: 'sweep',
      suggestions: [{section: 'sweep', value: 'name'}],
    },
    {
      title: 'config',
      suggestions: getSectionSuggestions('config').map(suggestion => ({
        section: 'config',
        value: suggestion,
      })),
    },
    {
      title: 'summary',
      suggestions: getSectionSuggestions('summary').map(suggestion => ({
        section: 'summary',
        value: suggestion,
      })),
    },
  ];
  return keySuggestions;
}

export function flatKeySuggestions(keySuggestions) {
  return _.flatMap(keySuggestions, section =>
    section.suggestions.map(
      suggestion =>
        section.title === 'run'
          ? suggestion.value
          : displayFilterKey(suggestion),
    ),
  );
}

export function setupKeyValueCounts(runs, keys, filters) {
  runs = filterRuns(filters, runs);
  let result = {};
  for (let key of keys) {
    let keyResult = {};
    for (let run of runs) {
      let value = getRunValue(run, key);
      let valueKey = sortableValue(value);
      if (_.isNil(keyResult[valueKey])) {
        keyResult[valueKey] = {value: valueKey, count: 0};
      }
      keyResult[valueKey].count++;
    }
    result[key] = keyResult;
  }
  return _.mapValues(result, valCounts =>
    _.sortBy(_.map(valCounts, val => val).filter(val => !_.isNil(val.value)), [
      'value',
    ]),
  );
}

export function getColumns(runs) {
  let configColumns = _.uniq(_.flatMap(runs, run => _.keys(run.config)))
    .sort()
    .map(col => 'config:' + col);
  let summaryColumns = _.uniq(_.flatMap(runs, run => _.keys(run.summary)))
    .filter(k => !k.startsWith('_') && k !== 'examples')
    .sort()
    .map(col => 'summary:' + col);
  let sweepColumns =
    runs && runs.findIndex(r => r.sweep) > -1 ? ['Sweep', 'Stop'] : [];
  return ['Description'].concat(
    sweepColumns,
    ['Ran', 'Runtime', 'Config'],
    configColumns,
    ['Summary'],
    summaryColumns,
  );
}

export function scatterPlotCandidates(configs, summaryMetrics) {
  /* We want to pull out configurations that a user might want to put in a scatterplot
   * For now that means configurations with more than two distinct numeric values
   */
  let configKeys = [];
  // get all the keys from all the configs

  configs.map((c, i) => {
    _.keys(c).map((key, j) => {
      configKeys.push(key);
    });
  });
  let k = _.uniq(configKeys);
  configKeys = k.filter((key, i) => {
    let vals = configs.map((c, i) => c[key]).filter(i => _.isFinite(i));
    return _.uniq(vals).length > 1;
  });
  configKeys = configKeys.map((key, i) => 'config:' + key);

  let summaryMetricKeys = [];
  summaryMetrics.map((c, i) => {
    _.keys(c).map((key, j) => {
      summaryMetricKeys.push(key);
    });
  });

  k = _.uniq(summaryMetricKeys);

  summaryMetricKeys = k.filter((key, i) => {
    let vals = summaryMetrics.map((c, i) => c[key]).filter(i => _.isFinite(i));
    return _.uniq(vals).length > 1;
  });
  summaryMetricKeys = summaryMetricKeys.map((key, i) => 'summary:' + key);

  return _.concat(configKeys, summaryMetricKeys);
}

export function groupByCandidates(configs) {
  /* We want to pull out the configurations that a user might want to groupBy
   * this would be any config that has more than one value that's different
   * and more than one values that is the same
   */
  let config_keys = new Set();
  // get all the keys from all the configs

  configs.map((c, i) => {
    _.keys(c).map((key, j) => {
      config_keys.add(key);
    });
  });
  let k = [...config_keys.keys()];
  var interesting = k.filter((key, i) => {
    var uniq = [...new Set(configs.map((c, i) => c[key]))];
    return uniq.length > 1 && uniq.length < configs.length;
  });
  return interesting;
}

export function groupConfigIdx(configs, key) {
  /* return a map from unique values of key in configs to array of indexes
  */
  let values = configs.map((c, i) => c.config[key]);
  let keyToGroup = {};
  values.map((key, i) => {
    if (!keyToGroup[key]) {
      keyToGroup[key] = [];
    }
    keyToGroup[key].push(i);
  });
  return keyToGroup;
}
