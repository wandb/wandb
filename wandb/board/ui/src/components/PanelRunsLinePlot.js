import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Button, List, Loader, Form} from 'semantic-ui-react';
import HelpIcon from '../components/HelpIcon';
import LinePlot from '../components/vis/LinePlot';
import {color} from '../util/colors.js';
import {registerPanelClass} from '../util/registry.js';
import {runDisplayName} from '../util/runhelpers.js';
import {addFilter} from '../actions/run';
import * as Query from '../util/query';

function smooth(data, smoothingWeight) {
  // data is array of x/y objects
  // x is always an index as this is used, so x-distance between each
  // successive point is equal.
  let last = data.length > 0 ? data[0].y : NaN;
  data.forEach(d => {
    if (!_.isFinite(last)) {
      d.smoothed = d.y;
    } else {
      // 1st-order IIR low-pass filter to attenuate the higher-
      // frequency components of the time-series.
      d.smoothed = last * smoothingWeight + (1 - smoothingWeight) * d.y;
    }
    last = d.smoothed;
  });
}

class RunsLinePlotPanel extends React.Component {
  static type = 'Run History Line Plot';
  static options = {};

  static validForData(data) {
    return data && !_.isNil(data.histories);
  }

  renderConfig() {
    let {keys} = this.props.data.histories;
    let options = keys.map(key => ({
      key: key,
      value: key,
      text: key,
    }));
    return (
      <Form>
        <Form.Field>
          <label>Smoothing</label>
          <input
            style={{width: '50%'}}
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
        <Form.Dropdown
          label="Y-Axis"
          placeholder="key"
          fluid
          search
          selection
          options={options}
          value={this.props.config.key}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, key: value})
          }
        />
        <Form.Group inline>
          <label>Y-Scale</label>
          <Form.Radio
            label="Linear"
            checked={
              !this.props.config.yScale || this.props.config.yScale === 'linear'
            }
            onChange={() =>
              this.props.updateConfig({
                ...this.props.config,
                yScale: 'linear',
              })
            }
          />
          <Form.Radio
            label="Log"
            checked={this.props.config.yScale === 'log'}
            onChange={() =>
              this.props.updateConfig({
                ...this.props.config,
                yScale: 'log',
              })
            }
          />
        </Form.Group>
      </Form>
    );
  }

  renderNormal() {
    let {loading, data, maxRuns, totalRuns} = this.props.data.histories;
    data = data.filter(run => this.props.data.filteredRunsById[run.name]);
    let key = this.props.config.key;
    let lines = data
      .map((runHistory, i) => {
        let lineData = runHistory.history.map((row, j) => ({
          x: j,
          y: row[key],
        }));
        if (this.props.config.smoothingWeight) {
          smooth(lineData, this.props.config.smoothingWeight || 0);
          lineData.forEach(point => (point.y = point.smoothed));
        }
        lineData = lineData.filter(point => !_.isNil(point.y));
        return {
          title: runDisplayName(
            this.props.data.filteredRunsById[runHistory.name],
          ),
          color: color(i),
          data: lineData,
        };
      })
      .filter(line => line.data.length > 0);
    let title = key;
    if (this.props.panelQuery && this.props.panelQuery.strategy === 'merge') {
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
        <h3 style={{display: 'inline'}}>
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
        </h3>
        <p style={{float: 'right'}}>
          {totalRuns > maxRuns && (
            <span>
              Limited to {maxRuns} of {totalRuns} selected runs{' '}
              <HelpIcon text="Run history plots are currently limited in the amount of data they can display. You can control runs displayed here by changing your selections." />
            </span>
          )}
        </p>
        <div style={{clear: 'both'}}>
          {this.props.data.base.length !== 0 &&
            data.length === 0 &&
            this.props.data.selectedRuns.length === 0 &&
            !loading && (
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
                    border: '1px solid #333',
                    padding: 15,
                  }}>
                  <p>
                    Select runs containing <i>{key}</i> in their history.
                    <HelpIcon
                      content={
                        <div>
                          <p>You can select runs by:</p>
                          <List bulleted>
                            <List.Item>
                              Highlighting regions or axes in charts
                            </List.Item>
                            <List.Item>
                              Checking them in the table below
                            </List.Item>
                            <List.Item>
                              Manually adding selections above.
                            </List.Item>
                          </List>
                        </div>
                      }
                    />
                  </p>
                  <p style={{textAlign: 'center'}}> - or - </p>
                  <p style={{textAlign: 'center'}}>
                    <Button
                      content="Select All"
                      onClick={() =>
                        this.props.addFilter(
                          'select',
                          {section: 'run', value: 'id'},
                          '=',
                          '*',
                        )
                      }
                    />{' '}
                    {this.props.data.filtered.length} runs.
                  </p>
                </div>
              </div>
            )}
          <LinePlot
            xAxis="index"
            yScale={this.props.config.yScale || 'linear'}
            lines={lines}
            sizeKey={this.props.sizeKey}
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
  return bindActionCreators({addFilter}, dispatch);
};

let ConnectRunsLinePlotPanel = connect(null, mapDispatchToProps)(
  RunsLinePlotPanel,
);
ConnectRunsLinePlotPanel.type = RunsLinePlotPanel.type;
ConnectRunsLinePlotPanel.options = RunsLinePlotPanel.options;
ConnectRunsLinePlotPanel.validForData = RunsLinePlotPanel.validForData;

registerPanelClass(ConnectRunsLinePlotPanel);
