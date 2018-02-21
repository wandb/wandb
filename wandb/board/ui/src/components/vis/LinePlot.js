import React from 'react';
import _ from 'lodash';
import {
  XAxis,
  YAxis,
  FlexibleWidthXYPlot,
  VerticalGridLines,
  HorizontalGridLines,
  LineSeries,
  DiscreteColorLegend,
  Crosshair,
} from 'react-vis';
import {displayValue} from '../../util/runhelpers.js';

export default class LinePlot extends React.Component {
  state = {disabled: {}, highlightX: null};

  _setup(props) {
    this.highlights = {};

    for (var line of props.lines) {
      for (var point of line.data) {
        if (_.isNil(this.highlights[point.x])) {
          this.highlights[point.x] = [];
        }
        this.highlights[point.x].push({
          title: line.title,
          color: line.color,
          y: point.y,
        });
      }
    }
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillReceiveProps(nextProps) {
    if (this.props.lines !== nextProps.lines) {
      this._setup(nextProps);
    }
  }

  render() {
    let maxLength = _.max(
      this.props.lines
        .filter(line => !this.state.disabled[line.title])
        .map(line => line.data.length),
    );
    let crosshairValues = null;
    if (this.state.highlightX && this.highlights[this.state.highlightX]) {
      crosshairValues = this.highlights[this.state.highlightX].map(point => ({
        ...point,
        x: this.state.highlightX,
      }));
    }
    return (
      <div
        style={{
          border: this.props.lines.length === 0 ? '1px solid #ccc' : '',
        }}>
        <DiscreteColorLegend
          orientation="horizontal"
          onItemClick={(item, i) => {
            console.log('item', item);
            this.setState({
              ...this.state,
              disabled: {
                ...this.state.disabled,
                [item.title]: !this.state.disabled[item.title],
              },
            });
          }}
          items={this.props.lines.map((line, i) => ({
            title: line.title,
            disabled: this.state.disabled[line.title],
            color: line.color,
          }))}
        />
        <FlexibleWidthXYPlot
          key={this.props.sizeKey}
          animation
          onMouseLeave={() => this.setState({...this.state, highlightX: null})}
          yType={this.props.yScale}
          height={240}>
          <VerticalGridLines />
          <HorizontalGridLines />
          <XAxis title={this.props.xAxis} />
          <YAxis />
          {this.props.lines
            .map(
              (line, i) =>
                !this.state.disabled[line.title] ? (
                  <LineSeries
                    key={i}
                    onNearestX={
                      line.data.length === maxLength
                        ? item =>
                            this.setState({...this.state, highlightX: item.x})
                        : null
                    }
                    color={line.color}
                    data={line.data}
                  />
                ) : null,
            )
            .filter(o => o)}
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
                {crosshairValues.sort((a, b) => b.y - a.y).map(point => (
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
      </div>
    );
  }
}
