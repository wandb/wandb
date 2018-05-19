import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Button, List, Loader, Form, Grid, Icon} from 'semantic-ui-react';
import HelpIcon from '../components/HelpIcon';
import LinePlot from '../components/vis/LinePlot';
import {registerPanelClass} from '../util/registry.js';
import '../components/PanelRunsLinePlot.css';
import {NavLink} from 'react-router-dom';

import {
  linesFromDataRunsPlot,
  xAxisLabels,
  xAxisLabel,
  xAxisChoicesRunsPlot,
  numericKeysFromHistories,
} from '../util/plotHelpers.js';

import * as Query from '../util/query';
import * as Run from '../util/runs';
import * as RunHelpers from '../util/runhelpers.js';
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
    return !_.isNil(data.base);
  }

  scaledSmoothness() {
    return Math.sqrt(this.props.config.smoothingWeight || 0) * 0.999;
  }

  _groupByOptions() {
    let configs = this.props.data.filtered.map((run, i) => run.config);

    let names = _.concat('None', RunHelpers.groupByCandidates(configs));
    return names.map((name, i) => ({
      text: name,
      key: name,
      value: name,
    }));
  }

  renderConfig() {
    if (!this.props.data.histories) {
      return <p>No Histories</p>;
    }
    // Warning: This assumes history keys match summary keys!
    const keys = this.props.data.axisOptions
      .map(Run.keyFromString)
      .filter(key => key.section === 'summary' && !_.startsWith(key.name, '_'))
      .map(key => key.name);
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

    let {loading, data} = this.props.data.histories;

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

    // Default to true.
    const yAxisAutoRange =
      this.props.config.yAxisAutoRange == null ||
      this.props.config.yAxisAutoRange;

    return (
      <div className="runs-line-plot">
        {!this.props.data.loading &&
          (!yAxisOptions || yAxisOptions.length == 0) && (
            <div className="ui negative message">
              <div className="header">No history data.</div>
              This project doesn't have any runs with history data, so you can't
              make a history line chart. For more information on how to collect
              history, check out our documentation at{' '}
              <a href="https://docs.wandb.com/docs/logs.html">
                https://docs.wandb.com/docs/logs.html
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
                  options={UI.makeOptions(this.props.data.keys)}
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
                  <Form.Group inline>
                    <Form.Field style={{width: 90}}>
                      <label style={{marginBottom: 10}}>Range</label>
                      <Form.Checkbox
                        label="Auto"
                        toggle
                        checked={yAxisAutoRange}
                        onClick={(e, {value}) =>
                          this.props.updateConfig({
                            ...this.props.config,
                            yAxisAutoRange: !yAxisAutoRange,
                          })
                        }
                      />
                    </Form.Field>
                    {!yAxisAutoRange && (
                      <Form.Input
                        label="min"
                        value={this.props.config.yAxisMin}
                        onChange={(e, {value}) =>
                          this.props.updateConfig({
                            ...this.props.config,
                            yAxisMin: value,
                          })
                        }
                      />
                    )}
                    {!yAxisAutoRange && (
                      <Form.Input
                        label="max"
                        value={this.props.config.yAxisMax}
                        onChange={(e, {value}) =>
                          this.props.updateConfig({
                            ...this.props.config,
                            yAxisMax: value,
                          })
                        }
                      />
                    )}
                  </Form.Group>
                </Form.Field>
              </Grid.Column>
              <Grid.Column
                width={2}
                verticalAlign="top"
                style={{marginTop: 18}}>
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
                      ? RunHelpers.displayValue(this.scaledSmoothness())
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
              {this.props.data.filtered.length > 1 && (
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

  renderNormal(mode = 'viewMode') {
    if (!this.props.data.histories) {
      // Not sure why this condition is happening.
      // TODO: fix.
      return <p>No Histories</p>;
    }
    let {data} = this.props.data.histories;
    let {loading} = this.props.data;
    const totalRuns = this.props.data.totalRuns;
    const maxRuns = this.props.data.limit;

    let yAxis = this.props.config.key;
    // Always show running Icon in legend.
    let legendSpec = (this.props.config.legendFields || ['name']).concat([
      'runningIcon',
    ]);

    let lines = linesFromDataRunsPlot(
      data,
      yAxis,
      this.props.config.xAxis || '_step',
      this.scaledSmoothness(),
      this.props.config.aggregate,
      this.props.config.groupBy || 'None',
      legendSpec,
      this.props.data,
      this.props.config.yLogScale
    );
    lines.map(
      (line, i) =>
        !line.area &&
        (line.mark = i < 5 ? 'solid' : i < 10 ? 'dashed' : 'dotted')
    );

    let title = '';
    if (yAxis) {
      if (Query.project(this.props.panelQuery)) {
        title = Query.project(this.props.panelQuery);
      } else {
        title = yAxis;
      }
      let querySummary = Query.summaryString(this.props.panelQuery);
      if (querySummary != null && querySummary !== '') {
        title = title + ' (' + querySummary + ')';
      }
    }

    let yDomain;
    if (
      this.props.config.yAxisAutoRange != null &&
      this.props.config.yAxisAutoRange === false &&
      this.props.config.yAxisMin != null &&
      this.props.config.yAxisMax != null
    ) {
      const yMin = parseFloat(this.props.config.yAxisMin);
      const yMax = parseFloat(this.props.config.yAxisMax);
      if (!_.isNaN(yMin) && !_.isNaN(yMax)) {
        yDomain = [yMin, yMax];
      }
    }

    title = (
      <h4 style={{display: 'inline'}}>
        {title}
        {loading && (
          <Loader
            style={{marginLeft: 6, marginBottom: 2}}
            active
            inline
            size="small"
          />
        )}
      </h4>
    );

    // Make a clickable title link if we're on the dashboard page
    if (this.props.pageQuery.entity && this.props.panelQuery.model) {
      title = (
        <NavLink
          style={{color: '#000'}}
          to={`/${this.props.pageQuery.entity}/${
            this.props.panelQuery.model
          }/runs`}>
          {title}
        </NavLink>
      );
    }

    return (
      <div>
        {title}
        <div style={{float: 'right', marginRight: 15}}>
          {totalRuns > maxRuns && (
            <span style={{fontSize: 13}}>
              Showing {maxRuns} of {totalRuns} selected runs{this.props.config
                .aggregate
                ? ' (before grouping)'
                : ' '}
            </span>
          )}
        </div>
        <div
          style={{
            clear: 'both',
          }}
          className={mode}>
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
            yAxis={yAxis}
            yScale={this.props.config.yLogScale ? 'log' : 'linear'}
            xScale={this.props.config.xLogScale ? 'log' : 'linear'}
            yDomain={yDomain}
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
          {this.renderNormal('editMode')}
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
