import React from 'react';
import _ from 'lodash';
import {
  XAxis,
  YAxis,
  FlexibleWidthXYPlot,
  VerticalGridLines,
  HorizontalGridLines,
  LineSeries,
  AreaSeries,
  DiscreteColorLegend,
  Crosshair,
  Borders,
} from 'react-vis';
import {Segment} from 'semantic-ui-react';

import {truncateString, displayValue} from '../../util/runhelpers.js';
import {smartNames} from '../../util/plotHelpers.js';
import {format} from 'd3-format';
import Highlight from './highlight.js';
import {Button, Container} from 'semantic-ui-react';

class LinePlotPlot extends React.PureComponent {
  // Implements the actual plot and data as a PureComponent, so that we don't
  // re-render every time the crosshair (highlight) changes.

  render() {
    const smallSizeThresh = 50;
    let {
      height,
      xAxis,
      yScale,
      lines,
      disabled,
      xScale,
      yAxis,
      onMouseUp,
      setRef,
      lastDrawLocation,
      crosshairCount,
      onBrushEnd,
    } = this.props;

    let xType = 'linear';
    if (xAxis == 'Absolute Time') {
      xType = 'time';
    } else if (xScale == 'log') {
      // this is not actually implemented
      xType = 'log';
    }

    if (!yAxis) {
      yAxis = '';
    }

    let nullGraph = false;
    let smallGraph = false;

    let maxDataLength = _.max(
      lines.filter(line => line.data.length).map((line, i) => line.data.length)
    );

    if (!maxDataLength) {
      nullGraph = true;
    } else if (
      maxDataLength < smallSizeThresh &&
      lines &&
      _.max(
        lines.map(
          (line, i) =>
            line ? _.max(line.data.map((points, i) => points.x)) : 0
        )
      ) < smallSizeThresh
    ) {
      if (maxDataLength < 2) {
        nullGraph = true;
      } else {
        smallGraph = true;
      }
    }

    return (
      // SML: I turned off animation, it was making stuff uncomfortably slow even
      // with the smallGraph detection.
      <FlexibleWidthXYPlot
        animation={false}
        xDomain={
          lastDrawLocation && [lastDrawLocation.left, lastDrawLocation.right]
        }
        yType={yScale}
        xType={xType}
        height={height}>
        {lines
          .map(
            (line, i) =>
              !disabled[line.title] ? (
                line.area ? (
                  <AreaSeries
                    key={i}
                    color={line.color}
                    data={line.data}
                    getNull={d => d.y !== null}
                    stroke={'#0000'}
                  />
                ) : (
                  <LineSeries
                    key={i}
                    color={line.color}
                    data={line.data}
                    getNull={d => d.y !== null}
                    strokeDasharray={
                      line.mark === 'dashed'
                        ? '4,2'
                        : line.mark === 'dotted' ? '1,1' : undefined
                    }
                    strokeStyle={'solid'}
                  />
                )
              ) : null
          )
          .filter(o => o)
          .reverse() // revese so the top line is the first line
        }
        <Borders style={{all: {fill: '#fff'}}} />
        <XAxis
          title={truncateString(xAxis)}
          tickTotal={5}
          tickValues={smallGraph ? _.range(1, smallSizeThresh) : null}
          tickFormat={xType != 'time' ? tick => format('.2s')(tick) : null}
          style={{
            line: {stroke: '999'},
            ticks: {stroke: '999'},
            text: {stroke: 'none', fill: 'aaa', fontWeight: 600},
          }}
        />
        <YAxis
          title={truncateString(yAxis)}
          tickValues={null}
          tickFormat={tick => format('.2r')(tick)}
          style={{
            line: {stroke: '999'},
            ticks: {stroke: '999'},
            text: {stroke: 'none', fill: 'aaa', fontWeight: 600},
          }}
        />
        <Highlight
          setRef={setRef}
          stepCount={crosshairCount}
          onMouseUp={onMouseUp}
          onBrushEnd={area => {
            onBrushEnd(area);
          }}
        />
      </FlexibleWidthXYPlot>
    );
  }
}

class LinePlotCrosshair extends React.PureComponent {
  // This doesn't contain the data, just the react-vis crosshair (the hover popup
  // that shows y-values at the current x-value).

  _setup(props) {
    // highlights is a map from x-value to list of y-information for each line at
    // that x-value
    this.highlights = {};

    let enabledLines = props.lines.filter(
      line => !props.disabled[line.title] && line.data.length > 0 && !line.aux
    );

    let longestLine = _.max(enabledLines.map(line => line.data.length));

    if (longestLine > 200) {
      // we're going to average points
      let maxX = _.max(
        enabledLines.map(line => {
          return line.data[line.data.length - 1].x;
        })
      );
      let minX = _.min(enabledLines.map(line => line.data[0].x));
      let steps = 50;
      let step = (maxX - minX) / 50;
      // we're gonna make an index for each line since they're sorted
      // and increment them until the x value is higher than our current slice
      let embededLinesIdx = enabledLines.map(line => 0);

      for (let i = 0; i < steps; i++) {
        let minSlice = i * step + minX;
        let maxSlice = (i + 1) * step + minX;
        let avgSlice = (i + 0.5) * step + minX;
        this.highlights[avgSlice] = [];

        for (let j = 0; j < embededLinesIdx.length; j++) {
          let data = [];
          let line = enabledLines[j];
          while (
            line.data[embededLinesIdx[j]] &&
            line.data[embededLinesIdx[j]].x < maxSlice
          ) {
            data.push(enabledLines[j].data[embededLinesIdx[j]].y);
            embededLinesIdx[j]++;
          }
          if (data.length > 0) {
            this.highlights[avgSlice].push({
              title: line.title.toString ? line.title.toString() : line.title,
              color: line.color,
              x: avgSlice,
              y: _.mean(data),
              mark: line.mark,
            });
          }
        }
      }
    } else {
      // we're going to calculate every point exactly
      for (var line of enabledLines) {
        for (var point of line.data) {
          if (_.isNil(this.highlights[point.x])) {
            this.highlights[point.x] = [];
          }
          this.highlights[point.x].push({
            title: line.title.toString ? line.title.toString() : line.title,
            color: line.color,
            x: point.x,
            y: point.y,
            mark: line.mark,
          });
        }
      }
    }

    // False line is a straight line that fits within the chart data. We render
    // it transparently and just use it for it's onNearestX callback.
    this.falseLine = [];
    if (enabledLines.length > 0) {
      let y = enabledLines[0].data[0].y;
      let xs = _.keys(this.highlights).map(k => Number(k));
      this.falseLine = xs.map(x => ({x: x, y: y}));
    }

    props.setCrosshairCount(this.falseLine.length);
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillReceiveProps(nextProps) {
    if (
      this.props.lines !== nextProps.lines ||
      this.props.disabled !== nextProps.disabled
    ) {
      this._setup(nextProps);
    }
  }

  render() {
    let {
      height,
      xAxis,
      highlightX,
      onMouseLeave,
      onHighlight,
      onMouseDown,
      lastDrawLocation,
    } = this.props;
    let crosshairValues = null;
    if (highlightX && this.highlights[highlightX]) {
      crosshairValues = this.highlights[highlightX];
    }

    return (
      <FlexibleWidthXYPlot
        animation={false}
        xDomain={
          lastDrawLocation && [lastDrawLocation.left, lastDrawLocation.right]
        }
        onMouseLeave={() => onMouseLeave()}
        height={height}
        onMouseDown={e => onMouseDown(e)}>
        <LineSeries
          onNearestX={item => onHighlight(item.x)}
          color="black"
          opacity={0}
          data={this.falseLine}
        />
        {crosshairValues &&
          crosshairValues.length > 0 && (
            <Crosshair values={crosshairValues}>
              <div
                style={{
                  color: '#333',
                  borderRadius: 6,
                  border: '1px solid #bbb',
                  minWidth: 160,
                  padding: 8,
                  background: 'white',
                  whiteSpace: 'nowrap',
                  lineHeight: '120%',
                }}>
                <b>
                  {this.props.xAxis + ': ' + displayValue(crosshairValues[0].x)}
                </b>
                {crosshairValues.sort((a, b) => b.y - a.y).map((point, i) => (
                  <div key={point.title + ' ' + i}>
                    <span
                      style={{
                        display: 'inline-block',
                        color: point.color,
                      }}>
                      <b fontSize="large">
                        {point.mark === 'dashed'
                          ? '┅'
                          : point.mark === 'dotted' ? '┉' : '━'}
                      </b>{' '}
                      <span style={{marginLeft: 6}}>
                        {point.title + ': ' + displayValue(point.y)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </Crosshair>
          )}
      </FlexibleWidthXYPlot>
    );
  }
}

export default class LinePlot extends React.PureComponent {
  state = {
    disabled: {},
    highlightX: null,
    hideCrosshair: false,
    lastDrawLocation: null,
    crosshairCount: 0,
  };

  constructor(props) {
    super(props);

    this.linePlotRef = null;

    this.setLinePlotRef = element => {
      this.linePlotRef = element;
    };
  }

  render() {
    const {lastDrawLocation} = this.state;
    let filteredLines = this.props.lines.filter(line => !line.aux);
    let lines = [];
    lines = filteredLines;
    return (
      <Segment attached="bottom" basic>
        <div
          className="line-plot-legend"
          style={{
            fontSize: 12,
            minHeight: 40,
            maxHeight: 60,
            overflow: 'scroll',
            overflowX: 'hidden',
            overflowY: 'hidden',
            lineHeight: '110%',
          }}>
          <div style={{verticalAlign: 'center'}}>
            {lines.map((line, i) => (
              <span
                key={i}
                style={{display: 'inline-block', marginRight: 16}}
                onClick={(item, i) => {
                  this.setState({
                    ...this.state,
                    disabled: {
                      ...this.state.disabled,
                      [item.title]: !this.state.disabled[item.title],
                    },
                  });
                }}>
                <span
                  className="line-plot-color"
                  style={{
                    display: 'inline-block',
                    color: line.color,
                  }}>
                  <b fontSize="large">
                    {line.mark === 'dashed'
                      ? '┅'
                      : line.mark === 'dotted' ? '┉' : '━'}
                  </b>
                </span>{' '}
                <span className="line-plot-title">
                  {line.title.toComponent
                    ? line.title.toComponent()
                    : line.title}
                </span>
              </span>
            ))}
          </div>
        </div>

        <div
          style={{position: 'relative'}}
          className={
            'line-plot-container' +
            (lastDrawLocation ? lastDrawLocation.classes : '')
          }>
          <LinePlotPlot
            height={this.props.currentHeight - 70 || 220}
            xAxis={this.props.xAxis}
            yAxis={this.props.yAxis}
            yScale={this.props.yScale}
            lines={this.props.lines}
            disabled={this.state.disabled}
            onMouseUp={() => this.setState({hideCrosshair: false})}
            setRef={e => this.setLinePlotRef(e)}
            lastDrawLocation={lastDrawLocation}
            crosshairCount={this.state.crosshairCount}
            onBrushEnd={area =>
              this.setState({
                lastDrawLocation: area,
              })
            }
          />
          <div
            style={{
              position: 'absolute',
              top: 0,
              width: '100%',
              pointerEvents: this.state.hideCrosshair ? 'none' : 'auto',
            }}>
            <LinePlotCrosshair
              height={this.props.currentHeight - 70 || 220}
              xAxis={this.props.xAxis}
              lines={this.props.lines}
              disabled={this.state.disabled}
              highlightX={this.state.highlightX}
              onMouseLeave={() => this.setState({highlightX: null})}
              onHighlight={xValue => this.setState({highlightX: xValue})}
              lastDrawLocation={lastDrawLocation}
              onMouseDown={e => {
                this.setState({hideCrosshair: true});
                const element = this.linePlotRef;
                let evt = new MouseEvent('mousedown', e.nativeEvent);
                element.dispatchEvent(evt);
              }}
              setCrosshairCount={count =>
                this.setState({crosshairCount: count})
              }
            />
          </div>
        </div>
      </Segment>
    );
  }
}
