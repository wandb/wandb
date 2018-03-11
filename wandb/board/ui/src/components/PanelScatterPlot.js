import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Form} from 'semantic-ui-react';
import {registerPanelClass} from '../util/registry.js';
import {
  convertValue,
  getRunValue,
  filterKeyFromString,
  filtersForAxis,
  scatterPlotCandidates,
} from '../util/runhelpers.js';
import {
  XAxis,
  YAxis,
  FlexibleWidthXYPlot,
  VerticalGridLines,
  HorizontalGridLines,
  MarkSeries,
  VerticalRectSeries,
  Hint,
} from 'react-vis';
import {batchActions} from 'redux-batched-actions';
import '../../node_modules/react-vis/dist/style.css';
import BoxSelection from './vis/BoxSelection';
import {addFilter, setHighlight} from '../actions/run';

class ScatterPlotPanel extends React.Component {
  static type = 'Scatter Plot';
  static options = {
    width: 8,
  };

  static validForData(data) {
    return !_.isNil(data.base);
  }

  constructor(props) {
    super(props);
    this.xSelect = {};
    this.ySelect = {};
    this.zSelect = {};
  }

  _setup(props, nextProps) {
    let {xAxis, yAxis, zAxis} = nextProps.config;
    if (nextProps.selections !== props.selections) {
      if (xAxis) {
        this.xSelect = filtersForAxis(nextProps.selections, xAxis);
      }
      if (yAxis) {
        this.ySelect = filtersForAxis(nextProps.selections, yAxis);
      }
      if (zAxis) {
        this.zSelect = filtersForAxis(nextProps.selections, zAxis);
      }
    }
  }

  _scatterPlotOptions() {
    let configs = this.props.data.filtered.map((run, i) => run.config);
    let summaryMetrics = this.props.data.filtered.map((run, i) => run.summary);

    let names = scatterPlotCandidates(configs, summaryMetrics);
    return names.map((name, i) => ({
      text: name,
      key: name,
      value: name,
    }));
  }

  componentWillMount() {
    this._setup({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    //for (var prop of _.keys(nextProps)) {
    //  console.log('prop equal?', prop, this.props[prop] === nextProps[prop]);
    //}
    this._setup(this.props, nextProps);
  }

  renderConfig() {
    let axisOptions = this._scatterPlotOptions(); //this.props.data;
    return (
      <Form>
        <Form.Dropdown
          label="X-Axis"
          placeholder="X-Axis"
          fluid
          search
          selection
          options={axisOptions}
          value={this.props.config.xAxis}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, xAxis: value})
          }
        />
        <Form.Dropdown
          label="Y-Axis"
          placeholder="Y-Axis"
          fluid
          search
          selection
          options={axisOptions}
          value={this.props.config.yAxis}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, yAxis: value})
          }
        />
        <Form.Dropdown
          label="Z-Axis (Color)"
          placeholder="Z-Axis"
          fluid
          search
          selection
          options={axisOptions}
          value={this.props.config.zAxis}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, zAxis: value})
          }
        />
      </Form>
    );
  }

  renderNormal() {
    let {xAxis, yAxis, zAxis} = this.props.config;

    if (this.props.data.filtered.length && xAxis && yAxis) {
      let data = this.props.data.filtered
        .map(run => {
          let point = {
            x: convertValue(getRunValue(run, xAxis)),
            y: convertValue(getRunValue(run, yAxis)),
            runId: run.name,
          };
          if (zAxis) {
            point.color = convertValue(getRunValue(run, zAxis));
          }
          return point;
        })
        .filter(point => point.x && point.y);
      let gradientData = [];
      if (zAxis) {
        data = data.filter(point => point.color);
        let zMin = _.min(data.map(o => o.color));
        let zMax = _.max(data.map(o => o.color));
        let breaks = 50;
        let range = zMax - zMin;
        let step = range / breaks;
        for (let i = 0; i < breaks; i++) {
          let val = zMin + step * i;
          gradientData.push({
            x0: val,
            x: val + step,
            y0: 0,
            y: 1,
            fill: val,
            color: val,
          });
        }
      }
      let highlight = _.find(
        data,
        point => point.runId === this.props.highlight,
      );
      return (
        <div>
          {zAxis && (
            <div>
              <FlexibleWidthXYPlot height={55}>
                <XAxis title={zAxis} />
                <VerticalRectSeries
                  colorRange={['#FF5733', '#33FF9C']}
                  fillRange={['#FF5733', '#33FF9C']}
                  data={gradientData}
                />
              </FlexibleWidthXYPlot>
            </div>
          )}
          <FlexibleWidthXYPlot height={300 - (zAxis ? 55 : 0)}>
            <VerticalGridLines />
            <HorizontalGridLines />
            <BoxSelection
              xSelect={this.xSelect}
              ySelect={this.ySelect}
              onSelectChange={(xSelect, ySelect) => {
                this.props.batchActions([
                  addFilter(
                    'select',
                    filterKeyFromString(xAxis),
                    '>',
                    xSelect.low,
                  ),
                  addFilter(
                    'select',
                    filterKeyFromString(xAxis),
                    '<',
                    xSelect.high,
                  ),
                  addFilter(
                    'select',
                    filterKeyFromString(yAxis),
                    '>',
                    ySelect.low,
                  ),
                  addFilter(
                    'select',
                    filterKeyFromString(yAxis),
                    '<',
                    ySelect.high,
                  ),
                ]);
              }}
            />
            <XAxis title={xAxis} />
            <YAxis title={yAxis} />
            <MarkSeries
              colorRange={['#FF5733', '#33FF9C']}
              data={data}
              onValueMouseOver={value => this.props.setHighlight(value.runId)}
              onValueMouseOut={value => this.props.setHighlight(null)}
            />
            {highlight &&
              highlight.color && (
                <Hint
                  value={highlight}
                  format={point => [{title: 'ID', value: point.runId}]}
                />
              )}
          </FlexibleWidthXYPlot>
        </div>
      );
    } else {
      return <p>Please configure X and Y axes first</p>;
    }
  }

  render() {
    if (this.props.configMode) {
      return (
        <div>
          {this.renderNormal()}
          {this.renderConfig()}
        </div>
      );
    } else {
      return this.renderNormal();
    }
  }
}

function mapStateToProps(state, ownProps) {
  return {
    selections: state.runs.filters.select,
    highlight: state.runs.highlight,
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({batchActions, setHighlight}, dispatch);
};

let ConnectScatterPlotPanel = connect(mapStateToProps, mapDispatchToProps)(
  ScatterPlotPanel,
);
ConnectScatterPlotPanel.type = ScatterPlotPanel.type;
ConnectScatterPlotPanel.options = ScatterPlotPanel.options;
ConnectScatterPlotPanel.validForData = ScatterPlotPanel.validForData;

registerPanelClass(ConnectScatterPlotPanel);
