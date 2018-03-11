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

class LinePlotPlot extends React.PureComponent {
  // Implements the actual plot and data as a PureComponent, so that we don't
  // re-render every time the crosshair (highlight) changes.
  render() {
    let {height, sizeKey, xAxis, yScale, lines, disabled, xScale} = this.props;
    let xType = 'linear';
    if (xAxis == 'Absolute Time') {
      xType = 'time';
    } else if (xScale == 'log') {
      xType = 'log';
    }

    let nullGraph = false;
    let smallGraph = false;

    let maxDataLength = _.max(lines.map((line, i) => line.data.length));

    if (
      maxDataLength < 20 &&
      lines &&
      _.max(
        lines.map(
          (line, i) =>
            line ? _.max(line.data.map((points, i) => points.x)) : 0,
        ),
      ) < 20
    ) {
      if (maxDataLength < 2) {
        nullGraph = true;
      }
      smallGraph = true;
    }

    return (
      <FlexibleWidthXYPlot
        key={sizeKey}
        yType={yScale}
        xType={xType}
        height={height}>
        <VerticalGridLines />
        <HorizontalGridLines />
        <XAxis
          title={xAxis}
          tickTotal={5}
          tickValues={smallGraph ? _.range(0, 20) : null}
        />
        <YAxis tickValues={nullGraph ? [0, 1, 2] : null} />

        {lines
          .map(
            (line, i) =>
              !disabled[line.title] ? (
                line.area ? (
                  <AreaSeries
                    key={i}
                    color={line.color}
                    data={line.data}
                    curve={smallGraph ? 'curveMonotoneX' : null}
                  />
                ) : (
                  <LineSeries
                    key={i}
                    color={line.color}
                    data={line.data}
                    curve={smallGraph ? 'curveMonotoneX' : null}
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
      line => !props.disabled[line.title] && line.data.length > 0,
    );

    for (var line of enabledLines) {
      for (var point of line.data) {
        if (_.isNil(this.highlights[point.x])) {
          this.highlights[point.x] = [];
        }
        this.highlights[point.x].push({
          title: line.title,
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
      let maxLength = _.max(enabledLines.map(line => line.data.length));
      let y = enabledLines[0].data[0].y;
      this.falseLine = _.range(0, maxLength).map(x => ({x: x, y: y}));
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
              <b>{this.props.xAxis + ': ' + crosshairValues[0].x}</b>
              {crosshairValues
                .sort((a, b) => b.y - a.y)
                .filter(point => !point.title.startsWith('_'))
                .map(point => (
                  <div key={point.title}>
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
    return (
      <div
        style={{
          border: this.props.lines.length === 0 ? '1px solid #ccc' : '',
        }}>
        <DiscreteColorLegend
          orientation="horizontal"
          onItemClick={(item, i) => {
            this.setState({
              ...this.state,
              disabled: {
                ...this.state.disabled,
                [item.title]: !this.state.disabled[item.title],
              },
            });
          }}
          items={this.props.lines
            .map((line, i) => ({
              title: truncateString(line.title, 40, 10),
              disabled: this.state.disabled[line.title],
              color: line.color,
            }))
            .filter(line => !line.title.startsWith('_'))}
        />
        <div style={{position: 'relative'}}>
          <LinePlotPlot
            height={this.props.currentHeight - 60 || 240}
            sizeKey={this.props.sizeKey}
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
