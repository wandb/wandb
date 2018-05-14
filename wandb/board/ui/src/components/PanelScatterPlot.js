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
import '../../node_modules/react-vis/dist/style.css';
import BoxSelection from './vis/BoxSelection';
import {setFilters, setHighlight} from '../actions/run';
import * as Selection from '../util/selections';
import * as Run from '../util/runs';

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
        this.xSelect = Selection.bounds(
          nextProps.selections,
          Run.keyFromString(xAxis)
        );
      }
      if (yAxis) {
        this.ySelect = Selection.bounds(
          nextProps.selections,
          Run.keyFromString(yAxis)
        );
      }
      if (zAxis) {
        this.zSelect = Selection.bounds(
          nextProps.selections,
          Run.keyFromString(zAxis)
        );
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
      <div>
        {(!axisOptions || axisOptions.length == 0) &&
          (this.props.data.filtered.length == 0 ? (
            <div class="ui negative message">
              <div class="header">No Runs</div>
              This project doesn't have any runs yet, or you have filtered all
              of the runs. To create a run, check out the getting started
              documentation.
              <a href="https://docs.wandb.com/docs/started.html">
                https://docs.wandb.com/docs/started.html
              </a>.
            </div>
          ) : (
            <div class="ui negative message">
              <div class="header">
                No useful configuration or summary metrics for Scatter Plot.
              </div>
              Scatter plot needs numeric configuration or summary metrics with
              more than one value. You don't have any of those yet. To learn
              more about collecting summary metrics check out our documentation
              at
              <a href="https://docs.wandb.com/docs/logs.html">
                https://docs.wandb.com/docs/logs.html
              </a>.
            </div>
          ))}
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
      </div>
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
        point => point.runId === this.props.highlight
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
          <FlexibleWidthXYPlot
            height={(this.props.currentHeight || 240) - (zAxis ? 55 : 0)}>
            <VerticalGridLines />
            <HorizontalGridLines />
            <BoxSelection
              xSelect={this.xSelect}
              ySelect={this.ySelect}
              onSelectChange={(xSelect, ySelect) => {
                let selections = this.props.selections;
                selections = Selection.Update.addBound(
                  selections,
                  Run.keyFromString(xAxis),
                  '>=',
                  xSelect.low
                );
                selections = Selection.Update.addBound(
                  selections,
                  Run.keyFromString(xAxis),
                  '<=',
                  xSelect.high
                );
                selections = Selection.Update.addBound(
                  selections,
                  Run.keyFromString(yAxis),
                  '>=',
                  ySelect.low
                );
                selections = Selection.Update.addBound(
                  selections,
                  Run.keyFromString(yAxis),
                  '<=',
                  ySelect.high
                );
                this.props.setFilters('select', selections);
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
  return bindActionCreators({setFilters, setHighlight}, dispatch);
};

let ConnectScatterPlotPanel = connect(mapStateToProps, mapDispatchToProps)(
  ScatterPlotPanel
);
ConnectScatterPlotPanel.type = ScatterPlotPanel.type;
ConnectScatterPlotPanel.options = ScatterPlotPanel.options;
ConnectScatterPlotPanel.validForData = ScatterPlotPanel.validForData;

registerPanelClass(ConnectScatterPlotPanel);
