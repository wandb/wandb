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
  if (!string) {
    return '';
  }
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

export function fuzzyMatchRegex(matchStr) {
  var regexpStr = '';
  for (var i = 0; i < matchStr.length; i++) {
    regexpStr += matchStr.charAt(i);
    regexpStr += '.*';
  }
  return new RegExp(regexpStr, 'i');
}

var indexMap = function(list) {
  /**
   *  For longestCommonSubstring, from
   * From https://github.com/mirkokiefer/longest-common-substring/blob/master/index.js
   */
  var map = {};
  _.forEach(list, (each, i) => {
    map[each] = map[each] || [];
    map[each].push(i);
  });
  return map;
};

function longestCommonSubstring(seq1, seq2) {
  /**
   * From https://github.com/mirkokiefer/longest-common-substring/blob/master/index.js
   */
  var result = {startString1: 0, startString2: 0, length: 0};
  var indexMapBefore = indexMap(seq1);
  var previousOverlap = [];
  _.forEach(seq2, (eachAfter, indexAfter) => {
    var overlapLength;
    var overlap = [];
    var indexesBefore = indexMapBefore[eachAfter] || [];
    indexesBefore.forEach(function(indexBefore) {
      overlapLength =
        ((indexBefore && previousOverlap[indexBefore - 1]) || 0) + 1;
      if (overlapLength > result.length) {
        result.length = overlapLength;
        result.startString1 = indexBefore - overlapLength + 1;
        result.startString2 = indexAfter - overlapLength + 1;
      }
      overlap[indexBefore] = overlapLength;
    });
    previousOverlap = overlap;
  });
  return result;
}

export function fuzzyMatchScore(str, matchStr) {
  /**
   * Returns the length of the longest common substring so that fuzzymatch
   * can sort on it.
   */
  return longestCommonSubstring(str, matchStr).length;
}

export function fuzzyMatch(strings, matchStr) {
  /**
   * fuzzyMatch replicates the command-P in vscode matching all the characters in order'
   * but not necessarily sequential
   */
  if (!matchStr) {
    return strings;
  }
  let matchedStrs = strings.filter(str => str.match(fuzzyMatchRegex(matchStr)));
  let scoredStrs = matchedStrs.map(str => {
    return {
      string: str,
      score: -1 * fuzzyMatchScore(str, matchStr),
    };
  });
  console.log('OY', scoredStrs);
  let sortedScores = _.sortBy(scoredStrs, ['score']);
  return sortedScores.map(ss => ss.string);
}

export function fuzzyMatchHighlight(
  str,
  matchStr,
  matchStyle = {backgroundColor: 'yellow'}
) {
  /**
   * fuzzyMatchHighlight works with fuzzyMatch to highlight the matching substrings
   */
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
          )
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

export function filterKeyFromString(s) {
  let [section, name] = s.split(':', 2);
  if (_.isNil(name)) {
    return {section: 'run', value: section};
  }
  return {section: section, value: name};
}

export function filtersForAxis(filters, axis) {
  let selections = _.values(filters);
  let sels = selections.filter(sel => Run.displayKey(sel.key) === axis);
  function getValueForOp(selections, op) {
    let opSel = _.find(selections, sel => sel.op === op);
    if (opSel) {
      return opSel.value;
    }
    return null;
  }
  return {low: getValueForOp(sels, '>'), high: getValueForOp(sels, '<')};
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
    // This is disabled, we were showing too many scary red X icons.
    return null;
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

export class RunsFancyName {
  /*
   * This makes a fancy name when you aggregate multiple runs.
   */

  constructor(runs, spec, prefix = '') {
    this._runs = runs;
    this._spec = spec;
    this._prefix = prefix;
  }
  toComponent() {
    if (!this._spec) {
      return runDisplayName(this._run);
    }
    return <span>{this._prefix} </span>;
  }
}

export class RunFancyName {
  constructor(runOrRuns, spec, prefix = '') {
    if (runOrRuns instanceof Array) {
      this._runs = runOrRuns;
    } else {
      this._runs = [runOrRuns];
    }
    this._spec = spec;
    this._prefix = prefix;
  }

  special = {
    createdAt: values => (
      <span key="createdAt">
        (started <TimeAgo date={new Date(_.min(values))} />){' '}
      </span>
    ),
    // FIXME: The stateicon probably shouldn't be just the state of the first entry
    stateIcon: () => stateToIcon(this._runs[0].state, 'stateIcon'),
    runningIcon: () =>
      _.some(this._runs, run => run.state === 'running')
        ? stateToIcon('running', 'runningIcon')
        : null,
  };

  toComponent() {
    if (!this._spec) {
      return runDisplayName(this._runs[0]);
    }
    return (
      <span>
        {this._prefix}{' '}
        {this._spec
          .map(key => {
            let values = this._runs.map(run => getRunValue(run, key));
            let specialFn = this.special[key];
            if (specialFn) {
              return specialFn(values);
            } else {
              if (_.isString(values[0])) {
                values = truncateString(values[0], 24);
              }
              return <span key={key}>{displayValue(values)} </span>;
            }
          })
          .filter(o => o)}
      </span>
    );
  }

  toString() {
    let str =
      this._prefix +
      this._spec
        .map(
          key =>
            this.special[key]
              ? null
              : this._runs.map(run => getRunValue(run, key)).join(', ')
        )
        .filter(o => o)
        .map(val => displayValue(val))
        .join(' ');
    return truncateString(str, 60);
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
    ['BucketType', 'v1', params.run, params.model, params.entity].join(':')
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
    oldBuckets.edges.map(edge => [edge.node.name, edge.node])
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
        name: suggestion,
      })),
    },
    {
      title: 'tags',
      suggestions: _.uniq(_.flatMap(runs, run => run.tags))
        .sort()
        .map(tag => ({
          section: 'tags',
          name: tag,
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
        name: suggestion,
      })),
    },
    {
      title: 'summary',
      suggestions: getSectionSuggestions('summary').map(suggestion => ({
        section: 'summary',
        name: suggestion,
      })),
    },
  ];
  return keySuggestions;
}

function autoCols(section, runs, minUniq) {
  runs = runs.filter(run => run[section]);
  if (runs.length <= 1) {
    return [];
  }
  let allKeys = _.uniq(_.flatMap(runs, run => _.keys(run[section])));
  let result = {};
  for (let key of allKeys) {
    let vals = runs.map(run => run[section][key]).filter(o => o != null);
    let types = _.uniq(vals.map(val => typeof val));
    if (vals.length === 0) {
      result[key] = false;
    } else if (types.length !== 1) {
      // Show columns that have different types
      result[key] = true;
    } else {
      let type = types[0];
      let uniqVals = _.uniq(vals);
      if (type === 'string') {
        // Show columns that have differing values unless all values differ
        if (uniqVals.length > 1 && uniqVals.length < vals.length) {
          result[key] = true;
        } else {
          result[key] = false;
        }
      } else {
        if (vals.every(val => _.isArray(val) && val.length === 0)) {
          // Special case for empty arrays, we don't get non-empty arrays
          // as config values because of the flattening that happens at a higher
          // layer.
          result[key] = false;
        } else if (
          vals.every(val => _.isObject(val) && _.keys(val).length === 0)
        ) {
          // Special case for empty objects.
          result[key] = false;
        } else {
          // Show columns that have differing values even if all values differ
          if (uniqVals.length > minUniq) {
            result[key] = true;
          } else {
            result[key] = false;
          }
        }
      }
    }
  }
  return _.map(result, (enable, key) => enable && key)
    .filter(o => o && !_.startsWith(o, '_'))
    .sort()
    .map(key => section + ':' + key);
}

export function getColumns(runs) {
  return [].concat(autoCols('config', runs, 1), autoCols('summary', runs, 0));
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
