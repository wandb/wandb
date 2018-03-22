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
} from 'react-vis';
import {truncateString, displayValue} from '../../util/runhelpers.js';
import {smartNames} from '../../util/plotHelpers.js';
import {format} from 'd3-format';

class LinePlotPlot extends React.PureComponent {
  // Implements the actual plot and data as a PureComponent, so that we don't
  // re-render every time the crosshair (highlight) changes.
  render() {
    const smallSizeThresh = 50;

    let {height, xAxis, yScale, lines, disabled, xScale} = this.props;
    let xType = 'linear';
    if (xAxis == 'Absolute Time') {
      xType = 'time';
    } else if (xScale == 'log') {
      // this is not actually implemented
      xType = 'log';
    }

    let nullGraph = false;
    let smallGraph = false;

    let maxDataLength = _.max(lines.map((line, i) => line.data.length));

    if (
      maxDataLength < smallSizeThresh &&
      lines &&
      _.max(
        lines.map(
          (line, i) =>
            line ? _.max(line.data.map((points, i) => points.x)) : 0,
        ),
      ) < smallSizeThresh
    ) {
      if (maxDataLength < 2) {
        nullGraph = true;
      }
      smallGraph = true;
    }

    return (
      <FlexibleWidthXYPlot
        margin={{left: 50}}
        animation={smallGraph}
        yType={yScale}
        xType={xType}
        height={height}>
        <VerticalGridLines />
        <HorizontalGridLines />
        <XAxis
          title={xAxis}
          tickTotal={5}
          tickValues={smallGraph ? _.range(1, smallSizeThresh) : null}
          tickFormat={tick => format('.2s')(tick)}
        />
        <YAxis
          tickValues={nullGraph ? [0, 1, 2] : null}
          tickFormat={tick => format('.2s')(tick)}
        />

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
                  />
                ) : (
                  <LineSeries
                    key={i}
                    color={line.color}
                    data={line.data}
                    nullAccessor={d => d.y !== null}
                  />
                )
              ) : null,
          )
          .filter(o => o)}
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
      line => !props.disabled[line.title] && line.data.length > 0 && !line.aux,
    );

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
        });
      }
    }

    // False line is a straight line that fits within the chart data. We render
    // it transparently and just use it for it's onNearestX callback.
    this.falseLine = [];
    if (enabledLines.length > 0) {
      let y = enabledLines[0].data[0].y;
      let xs = _.sortBy(
        _.uniq(
          _.flatMap(enabledLines, line => line.data.map(point => point.x)),
        ),
      );
      this.falseLine = xs.map(x => ({x: x, y: y}));
    }
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
    let {height, xAxis, highlightX, onMouseLeave, onHighlight} = this.props;
    let crosshairValues = null;
    if (highlightX && this.highlights[highlightX]) {
      crosshairValues = this.highlights[highlightX];
    }
    return (
      <FlexibleWidthXYPlot onMouseLeave={() => onMouseLeave()} height={height}>
        <LineSeries
          onNearestX={item => onHighlight(item.x)}
          color="black"
          opacity={0}
          data={this.falseLine}
        />
        {crosshairValues && (
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
              }}>
              <b>
                {this.props.xAxis + ': ' + displayValue(crosshairValues[0].x)}
              </b>
              {crosshairValues.sort((a, b) => b.y - a.y).map((point, i) => (
                <div key={point.title + ' ' + i}>
                  <span
                    style={{
                      display: 'inline-block',
                      backgroundColor: point.color,
                      width: 12,
                      height: 4,
                    }}
                  />
                  <span style={{marginLeft: 6}}>
                    {point.title + ': ' + displayValue(point.y)}
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
  state = {disabled: {}, highlightX: null};

  render() {
    let filteredLines = this.props.lines.filter(line => !line.aux);
    let lines = [];
    lines = filteredLines;
    return (
      <div
        style={{
          border: this.props.lines.length === 0 ? '1px solid #ccc' : '',
        }}>
        <div
          className="line-plot-legend"
          style={{
            fontSize: 11,
            minHeight: 40,
            maxHeight: 60,
            overflow: 'scroll',
            overflowX: 'hidden',
            overflowY: 'hidden',
          }}>
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
                  marginBottom: 2,
                  marginRight: 6,
                  backgroundColor: line.color,
                  width: 16,
                  height: 4,
                }}
              />
              <span className="line-plot-title">
                {line.title.toComponent ? line.title.toComponent() : line.title}
              </span>
            </span>
          ))}
        </div>
        <div style={{position: 'relative'}}>
          <LinePlotPlot
            height={this.props.currentHeight - 70 || 220}
            xAxis={this.props.xAxis}
            yScale={this.props.yScale}
            lines={this.props.lines}
            disabled={this.state.disabled}
          />
          <div style={{position: 'absolute', top: 0, width: '100%'}}>
            <LinePlotCrosshair
              height={240}
              xAxis={this.props.xAxis}
              lines={this.props.lines}
              disabled={this.state.disabled}
              highlightX={this.state.highlightX}
              onMouseLeave={() => this.setState({highlightX: null})}
              onHighlight={xValue => this.setState({highlightX: xValue})}
            />
          </div>
        </div>
      </div>
    );
  }
}
