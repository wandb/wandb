import React from 'react';

import _ from 'lodash';
import {color} from '../util/colors.js';
import {
  displayValue,
  runDisplayName,
  RunFancyName,
  groupConfigIdx,
  truncateString,
} from '../util/runhelpers.js';

const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;
const arrMax = arr => arr.reduce((a, b) => Math.max(a, b));
const arrMin = arr => arr.reduce((a, b) => Math.min(a, b));

export const xAxisLabels = {
  _step: 'Step',
  _runtime: 'Relative Time',
  _timestamp: 'Absolute Time',
};

function monotonicIncreasing(arr) {
  if (arr.length == 0) {
    return true;
  }
  let lastV = arr[0];
  for (let i = 1; i < arr.length; i++) {
    if (arr[i] < arr[i - 1]) {
      return false;
    }
  }
  return true;
}

export function friendlyMetricDefaults(metricNames) {
  /**
   * Friendly logic
   * 1) If there is a metric named acc use that along with metric val_acc if there.  This makes it work nicely with keras defaults.
   * 2) Otherwise, if there are metrics with the name "loss" use the first four of them
   * 3) Otherwise, if there is a metric with the name "accuracy" use that
   * 4) Otherwise pick the first four not named epoch or starting with _
   */
  let metrics = [];
  if (metricNames.filter(m => m === 'acc').length > 0) {
    metrics.push('acc');
    if (metricNames.filter(m => m === 'val_acc').length > 0) {
      metrics.push('val_acc');
    }
    return metrics;
  }

  if (metricNames.filter(m => /loss/i.test(m)).length > 0) {
    return metricNames.filter(m => /loss/i.test(m)).slice(0, 4);
  }

  if (metricNames.filter(m => /accuracy/i.test(m)).length > 0) {
    return metricNames.filter(m => /accuracy/i.test(m)).slice(0, 4);
  }

  return metricNames
    .filter(m => !m.startsWith('_'))
    .filter(m => m !== 'examples')
    .filter(m => m !== 'epoch')
    .slice(0, 4);
}

export function numericKeysFromHistories(histories) {
  /**
   * Removed image and other media types from histories object that looks like:
   * data Array(10)
   * - history Array(5)
   * - (0) {_runtime: 17.2080440521, _step: 0, _timestamp: 1521260275.848821, acc: 0.1971153846, epoch: 0, …}
   * - (1) {_runtime: 30.314109087, _step: 1, _timestamp: 1521260288.954887, acc: 0.3313301282, epoch: 1, …}
   * ...
   */
  let keys = histories.data.map(d => numericKeysFromHistory(d.history));
  return _.union(...keys);
}

export function numericKeysFromHistory(history) {
  /**
   * Removes the image and other media values from a history object
   */
  if (!history || history.length == 0) {
    return [];
  }

  return _.keys(history[0]).filter(
    k => !(history[0][k] && history[0][k]._type)
  ); // remove images and media
}

export function xAxisChoices(data) {
  return monotonicIncreasingNames(data, data.historyKeys);
}

export function xAxisChoicesRunsPlot(data, keys) {
  if (!data) {
    return [];
  }

  data = data.filter(runData => runData.history && runData.history.length > 2);

  if (data.length == 0) {
    return [];
  }

  let monotonicKeys = data.map(runData => {
    if (!runData.history || runData.history.length == 0) {
      return [];
    }
    let keys = _.keys(runData.history[0]); // we only consider the keys in the first record
    return monotonicIncreasingNames(runData, keys);
  });

  return _.intersection(...monotonicKeys);
}

export function monotonicIncreasingNames(data, historyKeys) {
  if (!historyKeys) {
    return [];
  }

  // ignore images and other media
  historyKeys = historyKeys.filter(k => {
    for (var i = 0; i < data.history.length; i++) {
      var row = data.history[i];
      if (row[k]) return Boolean(row[k]._type);
    }
  });

  if (historyKeys.length == 0) {
    return [];
  }

  let keysToData = {};
  historyKeys.map(k => (keysToData[k] = []));
  data.history.map(h => {
    _.keys(h).map(k => {
      if (_.includes(historyKeys, k)) {
        keysToData[k].push(h[k]);
      }
    });
  });

  return _.keys(keysToData)
    .filter(k => monotonicIncreasing(keysToData[k]))
    .filter(k => keysToData[k].length > 2);
}

export function xAxisLabel(xAxis, lines) {
  if (!xAxis) {
    return 'Step';
  }
  if (!lines || lines.length == 0) {
    return 'Time';
  }
  // all timesteps should be the same so we can just look at the first one
  let timestep = lines[0].timestep;
  let xAxisLabel = xAxisLabels[xAxis];
  if (xAxis === '_runtime') {
    xAxisLabel = 'Time' + (timestep ? ' (' + timestep + ')' : '');
  }

  return xAxisLabel;
}

export function appropriateTimestep(lines) {
  /**
   * Returns "seconds", "minutes", "hours", "days" depending on the
   * max values of lines.  Only appropriate if the x axis is relative time.
   */

  if (!lines || lines.length == 0) {
    return 'seconds';
  }
  let maxTime = 0;
  lines.map(l => {
    const last = _.last(l.data);
    if (last && last.x > maxTime) {
      maxTime = _.last(l.data).x;
    }
  });

  if (maxTime < 60 * 3) {
    return 'seconds';
  } else if (maxTime < 60 * 60 * 3) {
    return 'minutes';
  } else if (maxTime < 60 * 60 * 24 * 3) {
    return 'hours';
  } else {
    return 'days';
  }
}

export function convertSecondsToTimestep(
  lines,
  timestep = appropriateTimestep(lines)
) {
  /**
   * Converts all ther xAxis values to minutes hors or days by dividing by "factor"
   */
  let factor;
  if (timestep == 'seconds') {
    return;
  } else if (timestep == 'minutes') {
    factor = 60.0;
  } else if (timestep == 'hours') {
    factor = 60.0 * 60;
  } else if (timestep == 'days') {
    factor = 60.0 * 60 * 24;
  }
  lines.map(l => {
    l.data.map(p => {
      p.x = p.x / factor;
    });
    l.timestep = timestep;
  });
}

function filterNegative(lines) {
  /**
   * Iterate over all the lines and remove non-positive values for log scale
   */

  //TODO: This doesn't handle area graphs
  return lines.map((line, i) => {
    let newLine = line;
    newLine.data = line.data.map(point => {
      if (point.y <= 0) {
        point.y = null;
      }
      return point;
    });
    return newLine;
  });
}

export function smoothArea(data, smoothingWeight) {
  // LB: this is pretty ugly but areas have two numbers to smooth simultaneously y and y0
  // we will return smoothed and smoothed0
  // right now things are broken and I think this is the safest way to do it.
  // definitely should be refactored later
  let last = data.length > 0 ? 0 : NaN;
  let last0 = data.length > 0 ? 0 : NaN;

  let numAccum = 0;
  let numAccum0 = 0;

  data.forEach((d, i) => {
    let nextVal = d.y;
    if (!_.isFinite(last)) {
      d.smoothed = nextVal;
    } else {
      last = last * smoothingWeight + (1 - smoothingWeight) * nextVal;
      numAccum++;

      let debiasWeight = 1;
      if (smoothingWeight !== 1.0) {
        debiasWeight = 1.0 - Math.pow(smoothingWeight, numAccum);
      }
      d.smoothed = last / debiasWeight;
    }
    let nextVal0 = d.y0;
    if (!_.isFinite(last0)) {
      d.smoothed0 = nextVal0;
    } else {
      last0 = last0 * smoothingWeight + (1 - smoothingWeight) * nextVal0;
      numAccum0++;

      let debiasWeight = 1;
      if (smoothingWeight !== 1.0) {
        debiasWeight = 1.0 - Math.pow(smoothingWeight, numAccum0);
      }
      d.smoothed0 = last0 / debiasWeight;
    }
  });
}

export function smooth(data, smoothingWeight) {
  /** data is array of x/y objects
   * x is always an index as this is used, so x-distance between each
   * successive point is equal.
   * 1st-order IIR low-pass filter to attenuate the higher-
   * frequency components of the time-series.
   */
  let last = data.length > 0 ? 0 : NaN;
  let numAccum = 0;
  data.forEach((d, i) => {
    let nextVal = d.y;
    if (!_.isFinite(last)) {
      d.smoothed = nextVal;
    } else {
      last = last * smoothingWeight + (1 - smoothingWeight) * nextVal;
      numAccum++;
      // The uncorrected moving average is biased towards the initial value.
      // For example, if initialized with `0`, with smoothingWeight `s`, where
      // every data point is `c`, after `t` steps the moving average is
      // ```
      //   EMA = 0*s^(t) + c*(1 - s)*s^(t-1) + c*(1 - s)*s^(t-2) + ...
      //       = c*(1 - s^t)
      // ```
      // If initialized with `0`, dividing by (1 - s^t) is enough to debias
      // the moving average. We count the number of finite data points and
      // divide appropriately before storing the data.
      let debiasWeight = 1;
      if (smoothingWeight !== 1.0) {
        debiasWeight = 1.0 - Math.pow(smoothingWeight, numAccum);
      }
      d.smoothed = last / debiasWeight;
    }
  });
}

export function smoothLine(lineData, smoothingWeight, area = false) {
  /**
   * Scale lines by smoothingWeight
   * smoothingWeight should be between 0 and 1
   * uses tensorboard's smoothing algorithm
   *
   * Keeps the original lines passed in and adds a new line
   * with the name of the original line plus -smooth.
   */
  let smoothLineData = {name: lineData.name + '-smooth', data: []};
  if (smoothingWeight) {
    if (area) {
      smoothArea(lineData, smoothingWeight);
      smoothLineData = lineData.map(point => ({
        x: point.x,
        y: point.smoothed,
        y0: point.smoothed0,
      }));
    } else {
      smooth(lineData, smoothingWeight);
      smoothLineData = lineData.map(point => ({
        x: point.x,
        y: point.smoothed,
      }));
    }
  }
  return smoothLineData;
}

export function smoothLines(lines, smoothingWeight) {
  /**
   * Takes an array of lines and adds a new smoothed line for each
   * Line in the array.  Lightens the color of the original lines.
   */

  if (!(smoothingWeight && smoothingWeight > 0)) {
    return lines;
  }

  let smoothedLines = lines.map((line, i) => ({
    ...line,
    data: smoothLine(line.data, smoothingWeight, line.area),
  }));

  return _.concat(smoothedLines);
}

export function avgPointsByBucket(points, bucketCount, min, max) {
  /**
   *  Takes a bunch of points with x and y vals, puts them into fixed width buckets and
   *  returns the average y value per bucket.
   */

  let l = points.length;

  var inc = (max - min) / bucketCount;
  var buckets = new Array(bucketCount);
  for (let i = 0; i < bucketCount; i++) {
    buckets[i] = [];
  }

  for (let i = 0; i < l; i++) {
    if (points[i].x === max) buckets[bucketCount - 1].push(points[i]);
    else buckets[((points[i].x - min) / inc) | 0].push(points[i]);
  }

  let avgBuckets = buckets.map(
    (bucket, i) =>
      bucket.length > 0 ? avg(buckets[i].map((b, j) => b.y)) : NaN
  );
  return avgBuckets;
}

export function bucketsFromLines(lines) {
  let maxLengthRun = arrMax(lines.map(line => line.data.length));

  let xVals = _.flatten(
    lines.map((line, j) => line.data.map((point, i) => point.x))
  );

  if (xVals.length == 0) {
    return null;
  }

  let maxX = arrMax(xVals);
  let minX = arrMin(xVals);

  let bucketCount = Math.ceil(maxLengthRun / 2);
  return {maxX: maxX, minX: minX, bucketCount: bucketCount};
}

export function aggregateLines(
  lines,
  name, // for the legend
  idx,
  rawData, // for the legend
  buckets = null,
  nameSpec = null // for the legend
) {
  /**
   * Takes in a bunch of lines and returns a line with
   * the name Mean + name that plots the average of all the lines passed in
   * as well as a line with a y0 and a y coordinate for react vis
   * representing the min and the max.
   */

  let bucketXValues = [];
  let mergedBuckets = [];

  if (buckets) {
    /**
     * We aggregate lines by first bucketing them.  This is important when there
     * is sampling or when the x values don't line up.
     */

    let {maxX, minX, bucketCount} = buckets;

    // get all the data points in aligned buckets
    let bucketedLines = lines.map((line, j) =>
      avgPointsByBucket(line.data, bucketCount, minX, maxX)
    );

    // do a manual zip because lodash's zip is not like python
    bucketedLines.map((bucket, i) =>
      bucket.map((b, j) => {
        mergedBuckets[j] ? mergedBuckets[j].push(b) : (mergedBuckets[j] = [b]);
      })
    );

    // remove NaNs
    mergedBuckets = mergedBuckets.map((xBucket, i) =>
      xBucket.filter(y => isFinite(y))
    );

    let inc = (maxX - minX) / bucketCount;

    mergedBuckets.map(
      (xBucket, i) => (bucketXValues[i] = minX + (i + 0.5) * inc)
    );
  } else {
    let xVals = _.flatten(
      lines.map((line, j) => line.data.map((point, i) => point.x))
    );
    bucketXValues = _.uniq(xVals).sort((a, b) => a - b);
    let xValToBucketIndex = {};
    bucketXValues.map((val, i) => (xValToBucketIndex[val] = i));

    // get all the data points in buckets
    lines.map((line, j) =>
      line.data.map((point, j) => {
        let idx = xValToBucketIndex[point.x];
        mergedBuckets[idx]
          ? mergedBuckets[idx].push(point.y)
          : (mergedBuckets[idx] = [point.y]);
      })
    );
  }

  let lineData = mergedBuckets
    .filter(bucket => bucket && bucket.length > 0)
    .map((bucket, i) => ({
      x: bucketXValues[i],
      y: avg(bucket),
    }));

  let areaData = mergedBuckets
    .filter(bucket => bucket && bucket.length > 0)
    .map((bucket, i) => ({
      x: bucketXValues[i],
      y0: arrMin(bucket),
      y: arrMax(bucket),
    }));

  let prefix = 'Area ';
  let area = {
    title: new RunFancyName(rawData, nameSpec, prefix), //'area ' + name,
    aux: true,
    color: color(idx, 0.15),
    data: areaData,
    area: true,
  };

  prefix = 'Mean ' + name;
  let line = {
    title: new RunFancyName(rawData, nameSpec, prefix),
    color: color(idx),
    data: lineData,
  };
  return [line, area];
}

export function linesFromDataRunPlot(
  data,
  historyKeys,
  eventKeys,
  xAxis,
  smoothingWeight,
  yAxisLog = false
) {
  /**
   * This is to plot data for PanelLinePlot.
   * The object data has data.history (for most metrics) and data.events (for system metrics)
   * historyKeys - list of keys to find in history data structure.
   * eventKets - list of keys for find in events data structure.
   * xAxis - (String) - xAxis value
   * smoothingWeight - (number [0,1])
   * yAxisLog - is the yaxis log scale - this is to remove non-positive values pre-plot
   */

  const maxHistoryKeyCount = 8;
  const maxEventKeyCount = 8;

  let historyNames = historyKeys
    .filter(lineName => !_.startsWith(lineName, '_') && !(lineName === 'epoch'))
    .slice(0, maxHistoryKeyCount);

  let eventNames = eventKeys
    .filter(lineName => !_.startsWith(lineName, '_') && !(lineName === 'epoch'))
    .slice(0, maxEventKeyCount);

  let historyLines = historyNames
    .map((lineName, i) => {
      let lineData = data.history
        .map((row, j) => ({
          // __index is a legacy name - we should remove it from the logic
          // here at some point.
          x: xAxis === '__index' || xAxis === '_step' ? j : row[xAxis],
          y: row[lineName],
        }))
        .filter(point => !_.isNil(point.x) && !_.isNil(point.y));
      return {
        title: lineName,
        color: color(i),
        data: lineData,
      };
    })
    .filter(line => line.data.length > 0);

  let eventLines = eventNames
    .map((lineName, i) => {
      let lineData = data.events
        .map((row, j) => ({
          // __index is a legacy name - we should remove it from the logic
          // here at some point.
          x: xAxis === '__index' || xAxis === '_step' ? j : row[xAxis],
          y: row[lineName],
        }))
        .filter(point => !_.isNil(point.x) && !_.isNil(point.y));
      return {
        title: lineName,
        color: color(i + maxHistoryKeyCount),
        data: lineData,
      };
    })
    .filter(line => line.data.length > 0);

  let lines = _.concat(historyLines, eventLines);

  // TODO: The smoothing should probably happen differently if we're in log scale
  lines = smoothLines(lines, smoothingWeight);
  if (yAxisLog) {
    lines = filterNegative(lines);
  }
  if (xAxis == '_runtime') {
    convertSecondsToTimestep(lines);
  }
  return lines;
}

export function linesFromDataRunsPlot(
  data,
  key,
  xAxis,
  smoothingWeight,
  aggregate,
  groupBy,
  nameSpec,
  rawData,
  yAxisLog = false
) {
  /** Takes in data points and returns lines ready for passing
   * in to react-vis.
   * Inputs
   * data - data structure with all the runs
   * key - (String) yAxis value
   * xAxis - (String) - xAxis value
   * smoothingWeight - (number [0,1])
   * aggregate - (Boolean) should we aggregate
   * groupBy - (String or null) what config parameter should we aggregate by
   * nameSpec - (String or null) controls line titles (see runFancyName)
   * rawData - The data from this.props.data - needed for the legend
   * yAxisLog - is the yaxis log scale - this is to remove non-positive values pre-plot
   */

  if (!data || data.length == 0) {
    return [];
  }

  let xAxisKey = xAxis || '_step';

  let lines = data.map((runHistory, i) => ({
    name: runHistory.name,
    data: runHistory.history
      .map((row, j) => ({
        x: row[xAxisKey] || j, // Old runs might not have xAxisKey set
        y: row[key],
      }))
      .filter(point => !_.isNil(point.y)),
  }));

  if (xAxisKey == '_timestamp') {
    lines.map((line, i) => {
      line.data.map((points, j) => {
        points.x = points.x * 1000;
      });
    });
  }

  if (aggregate) {
    let bucketAggregation = true; // should we bucket the x values
    let maxLength = arrMax(lines.map((line, i) => line.data.length));
    let buckets = null;

    if (xAxisKey == '_step' && maxLength < 200) {
    } else {
      buckets = bucketsFromLines(lines);
    }

    let aggLines = [];
    if (groupBy && groupBy != 'None') {
      let groupIdx = groupConfigIdx(
        rawData.filtered.slice(0, lines.length),
        groupBy
      );
      let i = 0;
      _.forOwn(groupIdx, (idxArr, configVal) => {
        let lineGroup = [];
        let groupRawData = [];
        idxArr.map((idx, j) => {
          lineGroup.push(lines[idx]);
          groupRawData.push(rawData.filtered[idx]);
        });
        aggLines = _.concat(
          aggLines,
          aggregateLines(
            lineGroup,
            groupBy + ':' + displayValue(configVal),
            i++,
            groupRawData,
            buckets,
            nameSpec
          )
        );
      });
    } else {
      // aggregate everything
      aggLines = aggregateLines(lines, key, 0, rawData, buckets, nameSpec);
    }
    lines = aggLines;
  } else {
    lines = lines
      .filter(
        line => rawData.filteredRunsById[line.name] && line.data.length > 0
      )
      .map((line, i) => ({
        title: new RunFancyName(rawData.filteredRunsById[line.name], nameSpec),
        color: color(i, 0.8),
        data: line.data,
      }));
  }

  lines = smoothLines(lines, smoothingWeight);

  if (yAxisLog) {
    lines = filterNegative(lines);
  }

  if (xAxis == '_runtime') {
    convertSecondsToTimestep(lines);
  }

  return lines;
}

// Replace the longest common run in a set of strings.
function replaceLongestRun(names, minRunSize, replaceStr) {
  if (names.length <= 1) {
    return null;
  }
  let name0 = names[0];
  for (let runLen = name0.length; runLen >= minRunSize; runLen--) {
    for (let startPos = 0; startPos < name0.length - runLen + 1; startPos++) {
      let sub = name0.substring(startPos, startPos + runLen);
      if (sub.indexOf(replaceStr) >= 0) {
        continue;
      }
      let containsCount = 0;
      for (let checkName of names.slice(1)) {
        if (checkName.indexOf(sub) >= 0) {
          containsCount++;
        }
      }
      if (containsCount === names.length - 1) {
        return names.map(n => n.replace(sub, replaceStr));
      }
    }
  }
  return null;
}

// Given a set of names, return truncated versions that remove
// commonality
export function smartNames(names, minRunSize, replaceStr) {
  let i = 0;
  while (true) {
    let result = replaceLongestRun(names, minRunSize, '..');
    if (i > 5) {
      return names;
    }
    i++;
    if (result === null) {
      return names;
    }
    names = result;
  }
}

export function runToLegendLabels(run, fields) {}
