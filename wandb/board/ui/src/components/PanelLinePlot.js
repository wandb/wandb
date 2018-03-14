import React from 'react';
import _ from 'lodash';
import {Form, Grid, Icon, Button} from 'semantic-ui-react';
import {color} from '../util/colors.js';
import {registerPanelClass} from '../util/registry.js';
import LinePlot from '../components/vis/LinePlot';
import {linesFromLineData, xAxisLabels} from '../util/plotHelpers.js';
import {displayValue} from '../util/runhelpers.js';
class LinePlotPanel extends React.Component {
  static type = 'LinePlot';
  static options = {};

  static validForData(data) {
    return !_.isNil(data.history) && !_.isNil(data.historyKeys);
  }

  constructor(props) {
    super(props);
    this.props.config.xAxis = '_step';
  }

  scaledSmoothness() {
    return Math.sqrt(this.props.config.smoothingWeight || 0) * 0.999;
  }

  _selectedHistoryKeys() {
    /**
     * Return the currently selected keys with values in data.history
     */

    // L.B question: When does a historyKey have a key named examples?  Can we remove this?
    let historyKeys = this.props.data.historyKeys.filter(k => k !== 'examples');

    if (!this.props.config.lines) {
      return [];
    }

    let selectedHistoryKeys = [];
    this.props.config.lines.map((key, i) => {
      if (_.includes(historyKeys, key)) {
        selectedHistoryKeys.push(key);
      }
    });
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

  renderConfig() {
    let {historyKeys, eventKeys} = this.props.data;

    let yAxisKeys = _.concat(historyKeys, eventKeys);

    let xAxisOptions = [
      {text: xAxisLabels['_step'], key: '_step', value: '_step'},
      {text: 'Time', key: '_runtime', value: '_runtime'},
    ];
    if (this._selectedEventKeys().length > 0) {
      this.props.config.xAxis = '_runtime';
    }
    let yAxisOptions = yAxisKeys
      .filter(key => !key.startsWith('_'))
      .map(key => ({
        key: key,
        value: key,
        text: key,
      }));
    return (
      <Form>
        <Grid>
          <Grid.Row>
            <Grid.Column width={4}>
              <Form.Field>
                <Form.Dropdown
                  disabled={this._selectedEventKeys().length > 0}
                  label="X-Axis"
                  placeholder="X-Axis"
                  fluid
                  search
                  selection
                  options={xAxisOptions}
                  value={this.props.config.xAxis}
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
                  value={this.props.config.lines}
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
                  disabled={
                    !this.props.config.lines ||
                    this.props.config.lines.length == 0
                  }
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

  renderNormal() {
    let data = this.props.data;

    // By default show the first eight histories in the graph
    if (this.props.data.historyKeys && !this.props.config.lines) {
      this.props.config.lines = this.props.data.historyKeys.slice(0, 8);
    }

    if (!data) {
      // I'm not sure this ever happens?  Can we remove?
      return <p>This plot type is not supported on this page.</p>;
    }

    let eventKeys = this.props.data.eventKeys;
    let xAxis = this.props.config.xAxis;
    if (!xAxis) {
      xAxis = '_runtime';
    }

    let lines = linesFromLineData(
      data,
      this._selectedHistoryKeys(),
      this._selectedEventKeys(),
      xAxis,
      this.scaledSmoothness(),
    );

    return (
      <div>
        {(!this.props.data.history || this.props.data.history.length == 0) &&
          (!this.props.data.events || this.props.data.events.length == 0) && (
            <div
              style={{
                zIndex: 10,
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
                <p>
                  This run doesn't have any history data, so you can't make a
                  history line chart. For more information on how to collect
                  history, check out our documentation at{' '}
                  <a href="http://docs.wandb.com/#history">
                    http://docs.wandb.com/#history
                  </a>.
                </p>
              </div>
            </div>
          )}
        {_.isNil(this.props.config.lines) && (
          <div
            style={{
              zIndex: 10,
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
          lines={lines}
          xAxis={xAxisLabels[this.props.config.xAxis]}
          yScale={this.props.config.yLogScale ? 'log' : 'linear'}
          xScale={this.props.config.xLogScale ? 'log' : 'linear'}
        />
      </div>
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
