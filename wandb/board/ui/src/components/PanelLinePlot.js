import React from 'react';
import _ from 'lodash';
import {Form, Grid, Icon, Button} from 'semantic-ui-react';
import {color} from '../util/colors.js';
import {registerPanelClass} from '../util/registry.js';
import LinePlot from '../components/vis/LinePlot';
import {
  linesFromDataRunPlot,
  xAxisLabels,
  xAxisLabel,
  xAxisChoices,
  friendlyMetricDefaults,
} from '../util/plotHelpers.js';
import {displayValue} from '../util/runhelpers.js';

class LinePlotPanel extends React.Component {
  static type = 'LinePlot';
  static options = {};

  static validForData(data) {
    return !_.isNil(data.history) && !_.isNil(data.historyKeys);
  }

  constructor(props) {
    super(props);
  }

  scaledSmoothness() {
    return Math.sqrt(this.props.config.smoothingWeight || 0) * 0.999;
  }

  _selectedHistoryKeys() {
    /**
     * Return the currently selected keys with values in data.history
     */

    let historyKeys = this.props.data.historyKeys;

    // When not yet configured show friendly defaults
    if (historyKeys && _.isNil(this.props.config.lines)) {
      return friendlyMetricDefaults(historyKeys);
    }

    if (!this.props.config.lines) {
      return [];
    }

    let selectedHistoryKeys = this.props.config.lines.filter(
      key => !_.startsWith(key, '_') && _.includes(historyKeys, key),
    );
    return selectedHistoryKeys;
  }

  _selectedEventKeys() {
    /**
     * Return the currently selected keys with values in data.events
     */

    let eventKeys = this.props.data.eventKeys;

    if (!this.props.config.lines) {
      return [];
    }

    let selectedEventKeys = [];
    // hopefully can remove the filter key.startswith("_") at some point
    this.props.config.lines
      .filter(key => !key.startsWith('_'))
      .map((key, i) => {
        if (_.includes(eventKeys, key)) {
          selectedEventKeys.push(key);
        }
      });
    return selectedEventKeys;
  }

  _xAxis() {
    // Return the xAxis to use.
    let xAxis = this.props.config.xAxis || '_step';
    if (this._selectedEventKeys().length > 0) {
      xAxis = '_runtime';
    }
    return xAxis;
  }

  renderConfig() {
    let {historyKeys, eventKeys} = this.props.data;

    let yAxisKeys = _.concat(historyKeys, eventKeys);

    let xAxisOptions = [
      {text: xAxisLabels['_step'], key: '_step', value: '_step'},
      {text: 'Time', key: '_runtime', value: '_runtime'},
    ];

    let data = this.props.data;

    // LB I manually filter the keyword "epoch" from the xAxis options
    // How does it get in there?
    let newXAxisChoices = xAxisChoices(data).filter(key => !key === 'epoch');

    newXAxisChoices.filter(key => !key.startsWith('_')).map(xAxisChoice =>
      xAxisOptions.push({
        text: xAxisChoice,
        key: xAxisChoice,
        value: xAxisChoice,
      }),
    );

    // LB I manually filter the keyword "epoch" from the yAxis options
    // How does it get in there?
    let yAxisOptions = yAxisKeys
      .filter(key => !key.startsWith('_'))
      .filter(key => !(key === 'epoch'))
      .map(key => ({
        key: key,
        value: key,
        text: key,
      }));

    let selectedHistoryKeys = this._selectedHistoryKeys();
    let selectedEventKeys = this._selectedEventKeys();
    let selectedMetrics = _.concat(selectedHistoryKeys, selectedEventKeys);

    return (
      <Form>
        <Grid>
          <Grid.Row>
            <Grid.Column width={4}>
              <Form.Field>
                <Form.Dropdown
                  disabled={selectedEventKeys.length > 0}
                  label="X-Axis"
                  placeholder="X-Axis"
                  fluid
                  search
                  selection
                  options={xAxisOptions}
                  value={this._xAxis()}
                  onChange={(e, {value}) =>
                    this.props.updateConfig({
                      ...this.props.config,
                      xAxis: value,
                    })
                  }
                />
              </Form.Field>
            </Grid.Column>

            <Grid.Column width={10}>
              <Form.Field>
                <Form.Dropdown
                  label="Metrics"
                  placeholder="metrics"
                  fluid
                  multiple
                  search
                  selection
                  options={yAxisOptions}
                  value={selectedMetrics}
                  onChange={(e, {value}) =>
                    this.props.updateConfig({
                      ...this.props.config,
                      lines: value,
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
              <Form.Field>
                <label>
                  Smoothing:{' '}
                  {this.scaledSmoothness() > 0
                    ? displayValue(this.scaledSmoothness())
                    : 'None'}
                </label>
                <input
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
          </Grid.Row>
        </Grid>
      </Form>
    );
  }

  renderErrorChart(message) {
    return (
      <div>
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
            <Icon name="line chart" />
            {message}
          </div>
        </div>
        <LinePlot lines={[]} />
      </div>
    );
  }

  renderNormal() {
    let data = this.props.data;

    if (!data) {
      // I'm not sure this ever happens?  Can we remove?
      return <p>This plot type is not supported on this page.</p>;
    }

    let eventKeys = this.props.data.eventKeys;

    let xAxis = this._xAxis();

    let selectedHistoryKeys = this._selectedHistoryKeys();
    let selectedEventKeys = this._selectedEventKeys();
    let selectedMetrics = _.concat(selectedHistoryKeys, selectedEventKeys);

    let lines = linesFromDataRunPlot(
      data,
      selectedHistoryKeys,
      selectedEventKeys,
      xAxis,
      this.scaledSmoothness(),
      this.props.config.yLogScale,
    );

    if (
      (!this.props.data.history || this.props.data.history.length == 0) &&
      (!this.props.data.events || this.props.data.events.length == 0)
    ) {
      return this.renderErrorChart(
        <p>
          This run doesn't have any history data, so you can't make a history
          line chart. For more information on how to collect history, check out
          our documentation at{' '}
          <a href="http://docs.wandb.com/#history">
            http://docs.wandb.com/#history
          </a>.
        </p>,
      );
    }
    if (selectedMetrics.length == 0) {
      return this.renderErrorChart(<div>This chart isn't configured yet.</div>);
    }

    if (lines.every(l => l.data.length == 0)) {
      return this.renderErrorChart(<div>This chart has no data.</div>);
    }

    return (
      <LinePlot
        lines={lines}
        xAxis={xAxisLabel(xAxis, lines)}
        yScale={this.props.config.yLogScale ? 'log' : 'linear'}
        xScale={this.props.config.xLogScale ? 'log' : 'linear'}
      />
    );
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
registerPanelClass(LinePlotPanel);
