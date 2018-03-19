import React from 'react';

import _ from 'lodash';
import {color} from '../util/colors.js';
import {
  displayValue,
  runDisplayName,
  groupConfigIdx,
} from '../util/runhelpers.js';

const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;
const arrMax = arr => arr.reduce((a, b) => Math.max(a, b));
const arrMin = arr => arr.reduce((a, b) => Math.min(a, b));

export const xAxisLabels = {
  _step: 'Step',
  _runtime: 'Relative Time (sec)',
  _timestamp: 'Absolute Time',
};

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

export function smoothLine(lineData, smoothingWeight) {
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
    smooth(lineData, smoothingWeight);
    smoothLineData = lineData.map(point => ({
      x: point.x,
      y: point.smoothed,
    }));
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

  // we want to leave alone the lines starting with _
  let specialLines = lines.filter(line => line.title.startsWith('_'));

  let smoothedLines = lines
    .filter(line => !line.title.startsWith('_'))
    .map((line, i) => {
      return {
        data: smoothLine(line.data, smoothingWeight),
        title: line.title,
        color: color(i, 0.8),
        name: line.name,
      };
    });

  // we want to leave a light trace of the original lines (except those starting with _)
  let origLines = lines
    .filter(line => !line.title.startsWith('_'))
    .map((line, i) => {
      let newLine = line;
      newLine.title = '_' + newLine.title;
      newLine.color = color(i, 0.1);
      return newLine;
    });
  return _.concat(specialLines, origLines, smoothedLines);
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
      bucket.length > 0 ? avg(buckets[i].map((b, j) => b.y)) : NaN,
  );
  return avgBuckets;
}

export function aggregateLines(lines, name, idx, bucketData = true) {
  /**
   * Takes in a bunch of lines and returns a line with
   * the name Mean + name that plots the average of all the lines passed in
   * as well as a line with a y0 and a y coordinate for react vis
   * representing the min and the max.
   */

  let maxLengthRun = arrMax(lines.map(line => line.data.length));

  let xVals = _.flatten(
    lines.map((line, j) => line.data.map((point, i) => point.x)),
  );

  if (xVals.length == 0) {
    return [];
  }

  let maxX = arrMax(xVals);
  let minX = arrMin(xVals);
  let bucketXValues = [];
  let mergedBuckets = [];

  if (bucketData) {
    /**
     * We aggregate lines by first bucketing them.  This is important when there
     * is sampling or when the x values don't line up.
     */
    let bucketCount = Math.ceil(maxLengthRun / 2);

    // get all the data points in aligned buckets
    let bucketedLines = lines.map((line, j) =>
      avgPointsByBucket(line.data, bucketCount, minX, maxX),
    );

    // do a manual zip because lodash's zip is not like python
    bucketedLines.map((bucket, i) =>
      bucket.map((b, j) => {
        mergedBuckets[j] ? mergedBuckets[j].push(b) : (mergedBuckets[j] = [b]);
      }),
    );

    // remove NaNs
    mergedBuckets = mergedBuckets.map((xBucket, i) =>
      xBucket.filter(y => isFinite(y)),
    );

    let inc = (maxX - minX) / bucketCount;

    mergedBuckets.map(
      (xBucket, i) => (bucketXValues[i] = minX + (i + 0.5) * inc),
    );
  } else {
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
      }),
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

  let area = {
    title: '_area ' + name,
    color: color(idx, 0.3),
    data: areaData,
    area: true,
  };

  let line = {
    title: 'Mean ' + name,
    color: color(idx),
    data: lineData,
  };
  return [line, area];
}

export function linesFromLineData(
  data,
  historyKeys,
  eventKeys,
  xAxis,
  smoothingWeight,
  yAxisLog = false,
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
  return lines;
}

export function linesFromData(
  data,
  key,
  xAxis,
  smoothingWeight,
  aggregate,
  groupBy,
  rawData,
  yAxisLog = false,
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
   * rawData - The data from this.props.data TODO: Why do we need this??
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
    if (xAxisKey == '_step' && maxLength < 200) {
      bucketAggregation = false;
    }

    let aggLines = [];
    if (groupBy && groupBy != 'None') {
      let groupIdx = groupConfigIdx(
        rawData.selectedRuns.slice(0, lines.length),
        groupBy,
      );
      let i = 0;
      _.forOwn(groupIdx, (idxArr, configVal) => {
        let lineGroup = [];
        idxArr.map((idx, j) => {
          lineGroup.push(lines[idx]);
        });
        aggLines = _.concat(
          aggLines,
          aggregateLines(
            lineGroup,
            key + ' ' + groupBy + ':' + displayValue(configVal),
            i++,
            bucketAggregation,
          ),
        );
      });
    } else {
      aggLines = aggregateLines(lines, key, 0, bucketAggregation);
    }
    lines = aggLines;
  } else {
    lines = lines.filter(line => line.data.length > 0).map((line, i) => ({
      title: runDisplayName(
        rawData ? rawData.filteredRunsById[line.name] : line.name,
      ),
      color: color(i, 0.8),
      data: line.data,
    }));
  }

  lines = smoothLines(lines, smoothingWeight);

  if (yAxisLog) {
    lines = filterNegative(lines);
  }

  return lines;
}
