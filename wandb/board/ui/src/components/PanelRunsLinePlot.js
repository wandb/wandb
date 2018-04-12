import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Button, List, Loader, Form, Grid, Icon} from 'semantic-ui-react';
import HelpIcon from '../components/HelpIcon';
import LinePlot from '../components/vis/LinePlot';
import {registerPanelClass} from '../util/registry.js';

import {
  linesFromDataRunsPlot,
  xAxisLabels,
  xAxisLabel,
  xAxisChoicesRunsPlot,
  numericKeysFromHistories,
} from '../util/plotHelpers.js';

import * as Query from '../util/query';
import * as Run from '../util/runhelpers.js';
import * as RunHelpers2 from '../util/runhelpers2';
import * as UI from '../util/uihelpers.js';

class RunsLinePlotPanel extends React.Component {
  static type = 'Run History Line Plot';
  static yAxisOptions = {};
  static xAxisOptions = {};
  static groupByOptions = {};

  constructor(props) {
    super(props);
    this.keySuggestions = [];
  }

  static validForData(data) {
    return data && !_.isNil(data.histories);
  }

  _setupKeySuggestions(props) {
    const keyValueCounts = RunHelpers2.keyValueCounts(
      props.data.filtered,
      Run.flatKeySuggestions(props.data.keys)
    );
    // Show keys that have at least one value.
    this.keySuggestions = _.map(
      keyValueCounts,
      (valueCounts, key) => (_.keys(valueCounts).length >= 1 ? key : null)
    ).filter(o => o);
  }

  componentWillMount() {
    this._setupKeySuggestions(this.props);
  }

  componentWillReceiveProps(nextProps) {
    if (
      this.props.data.filtered !== nextProps.data.filtered ||
      this.props.data.keys !== nextProps.data.keys
    ) {
      this._setupKeySuggestions(nextProps);
    }
  }

  scaledSmoothness() {
    return Math.sqrt(this.props.config.smoothingWeight || 0) * 0.999;
  }

  _groupByOptions() {
    let configs = this.props.data.selectedRuns.map((run, i) => run.config);

    let names = _.concat('None', Run.groupByCandidates(configs));
    return names.map((name, i) => ({
      text: name,
      key: name,
      value: name,
    }));
  }

  renderConfig() {
    // LB note this maybe should move to RunsDataLoader?
    // the point of this is to remove histories that aren't numerical (images)
    // and special histories that start with _
    let keys = numericKeysFromHistories(this.props.data.histories).filter(
      key => !key.startsWith('_')
    );
    let yAxisOptions = keys.map(key => ({
      key: key,
      value: key,
      text: key,
    }));

    let xAxisOptions = [
      {text: xAxisLabels['_step'], key: '_step', value: '_step'},
      {text: xAxisLabels['_runtime'], key: '_runtime', value: '_runtime'},
      {text: xAxisLabels['_timestamp'], key: '_timestamp', value: '_timestamp'},
    ];

    let {loading, data, maxRuns, totalRuns} = this.props.data.histories;

    let newXAxisChoices = xAxisChoicesRunsPlot(data);
    newXAxisChoices
      .filter(key => !key.startsWith('_'))
      .filter(key => !(key === 'epoch'))
      .map(xAxisChoice =>
        xAxisOptions.push({
          text: xAxisChoice,
          key: xAxisChoice,
          value: xAxisChoice,
        })
      );

    let groupByOptions = {};
    let disabled = this.props.data.histories.data.length === 0;

    return (
      <div>
        {!this.props.data.loading &&
          (!yAxisOptions || yAxisOptions.length == 0) && (
            <div className="ui negative message">
              <div className="header">No history data.</div>
              This project doesn't have any runs with history data, so you can't
              make a history line chart. For more information on how to collect
              history, check out our documentation at{' '}
              <a href="http://docs.wandb.com/#history">
                http://docs.wandb.com/#history
              </a>.
            </div>
          )}
        <Form style={{marginTop: 10}}>
          <Grid>
            <Grid.Row verticalAlign="middle">
              <Grid.Column width={7}>
                <Form.Dropdown
                  disabled={disabled}
                  label="Legend Fields"
                  placeholder="Legend Fields"
                  fluid
                  search
                  multiple
                  selection
                  options={UI.makeOptions(this.keySuggestions)}
                  value={this.props.config.legendFields || ['name']}
                  onChange={(e, {value}) =>
                    this.props.updateConfig({
                      ...this.props.config,
                      legendFields: value,
                    })
                  }
                />
              </Grid.Column>
            </Grid.Row>
            <Grid.Row>
              <Grid.Column width={7}>
                <Form.Field>
                  <Form.Dropdown
                    disabled={!this.props.config.key}
                    label="X-Axis"
                    placeholder="xAxis"
                    fluid
                    search
                    selection
                    options={xAxisOptions}
                    value={this.props.config.xAxis || '_step'}
                    onChange={(e, {value}) =>
                      this.props.updateConfig({
                        ...this.props.config,
                        xAxis: value,
                      })
                    }
                  />
                </Form.Field>
              </Grid.Column>

              <Grid.Column width={7}>
                <Form.Field>
                  <Form.Dropdown
                    disabled={disabled}
                    label="Y-Axis"
                    placeholder="key"
                    fluid
                    search
                    selection
                    options={yAxisOptions}
                    value={this.props.config.key}
                    onChange={(e, {value}) =>
                      this.props.updateConfig({
                        ...this.props.config,
                        key: value,
                      })
                    }
                  />
                </Form.Field>
              </Grid.Column>
              <Grid.Column width={2} verticalAlign="bottom">
                <Button
                  animated="vertical"
                  toggle
                  active={this.props.config.yLogScale}
                  onClick={(e, {value}) =>
                    this.props.updateConfig({
                      ...this.props.config,
                      yLogScale: !this.props.config.yLogScale,
                    })
                  }>
                  <Button.Content visible>
                    <Icon className="natural-log" size="large" align="center" />
                  </Button.Content>
                  <Button.Content hidden>Log</Button.Content>
                </Button>
              </Grid.Column>
            </Grid.Row>
            <Grid.Row>
              <Grid.Column width={6}>
                <Form.Field disabled={disabled}>
                  <label>
                    Smoothing:{' '}
                    {this.scaledSmoothness() > 0
                      ? Run.displayValue(this.scaledSmoothness())
                      : 'None'}
                  </label>
                  <input
                    disabled={!this.props.config.key}
                    type="range"
                    min={0}
                    max={1}
                    step={0.001}
                    value={this.props.config.smoothingWeight || 0}
                    onChange={e => {
                      this.props.updateConfig({
                        ...this.props.config,
                        smoothingWeight: parseFloat(e.target.value),
                      });
                    }}
                  />
                </Form.Field>
              </Grid.Column>
              {this.props.data.selectedRuns.length > 1 && (
                <Grid.Column width={4} verticalAlign="middle">
                  <Form.Checkbox
                    toggle
                    disabled={!this.props.config.key}
                    checked={this.props.config.aggregate}
                    label="Aggregate Runs"
                    name="aggregate"
                    onChange={(e, value) =>
                      this.props.updateConfig({
                        ...this.props.config,
                        aggregate: value.checked,
                      })
                    }
                  />
                </Grid.Column>
              )}
              {this.props.config.aggregate && (
                <Grid.Column width={6}>
                  <Form.Dropdown
                    disabled={!this.props.config.aggregate}
                    label="Group By"
                    placeholder="groupBy"
                    fluid
                    search
                    selection
                    options={this._groupByOptions()}
                    value={this.props.config.groupBy || 'None'}
                    onChange={(e, {value}) =>
                      this.props.updateConfig({
                        ...this.props.config,
                        groupBy: value,
                      })
                    }
                  />
                </Grid.Column>
              )}
            </Grid.Row>
          </Grid>
        </Form>
      </div>
    );
  }

  renderNormal() {
    if (!this.props.data.histories) {
      // Not sure why this condition is happening.
      // TODO: fix.
      return <p>No Histories</p>;
    }
    let {loading, data, maxRuns, totalRuns} = this.props.data.histories;

    let key = this.props.config.key;
    // Always show running Icon in legend.
    let legendSpec = (this.props.config.legendFields || ['name']).concat([
      'runningIcon',
    ]);

    let lines = linesFromDataRunsPlot(
      data,
      key,
      this.props.config.xAxis || '_step',
      this.scaledSmoothness(),
      this.props.config.aggregate,
      this.props.config.groupBy || 'None',
      legendSpec,
      this.props.data,
      this.props.config.yLogScale
    );
    let title = key;
    if (Query.strategy(this.props.panelQuery) === 'merge') {
      let querySummary = Query.summaryString(this.props.panelQuery);
      if (querySummary) {
        title += ' (' + querySummary + ')';
      }
      if (this.props.panelQuery.model) {
        title = this.props.panelQuery.model + ':' + title;
      }
    }
    return (
      <div>
        <h4 style={{display: 'inline'}}>
          {title}
          {loading &&
            data.length < maxRuns && (
              <Loader
                style={{marginLeft: 6, marginBottom: 2}}
                active
                inline
                size="small"
              />
            )}
        </h4>
        <div style={{float: 'right', marginRight: 10}}>
          {totalRuns > maxRuns && (
            <span style={{fontSize: 13}}>
              {/* <HelpIcon text="Run history plots are currently limited in the amount of data they can display. You can control runs displayed here by changing your selections." /> */}
              Showing {maxRuns} of {totalRuns} selected runs{' '}
            </span>
          )}
        </div>
        <div style={{clear: 'both'}}>
          {_.isNil(this.props.config.key) && (
            <div
              style={{
                position: 'absolute',
                height: 200,
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
              <div
                style={{
                  maxWidth: 300,
                  backgroundColor: 'white',
                  border: '1px dashed #999',
                  padding: 15,
                  color: '#666',
                }}>
                <p>
                  {' '}
                  <Icon name="line chart" />
                  This chart isn't configured yet.
                </p>
              </div>
            </div>
          )}
          <LinePlot
            xAxis={xAxisLabel(this.props.config.xAxis, lines)}
            yScale={this.props.config.yLogScale ? 'log' : 'linear'}
            xScale={this.props.config.xLogScale ? 'log' : 'linear'}
            lines={lines}
            sizeKey={this.props.sizeKey}
            currentHeight={this.props.currentHeight}
          />
        </div>
      </div>
    );
  }

  render() {
    this.lines = this.props.config.lines || [];
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
registerPanelClass(RunsLinePlotPanel);

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({}, dispatch);
};

let ConnectRunsLinePlotPanel = connect(null, mapDispatchToProps)(
  RunsLinePlotPanel
);
ConnectRunsLinePlotPanel.type = RunsLinePlotPanel.type;
ConnectRunsLinePlotPanel.options = RunsLinePlotPanel.yAxisOptions;
ConnectRunsLinePlotPanel.validForData = RunsLinePlotPanel.validForData;

registerPanelClass(ConnectRunsLinePlotPanel);
