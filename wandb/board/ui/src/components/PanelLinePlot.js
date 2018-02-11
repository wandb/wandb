import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {
  Button,
  Card,
  Dropdown,
  Grid,
  Form,
  Header,
  Popup,
} from 'semantic-ui-react';
import {color} from '../util/colors.js';
import {registerPanelClass} from '../util/registry.js';
import {displayValue} from '../util/runhelpers.js';
import LinePlot from '../components/vis/LinePlot';

class LinePlotPanel extends React.Component {
  static type = 'LinePlot';
  static options = {};

  static validForData(data) {
    return !_.isNil(data.history) && !_.isNil(data.historyKeys);
  }

  renderConfig() {
    let {historyKeys, history, eventKeys, events} = this.props.data;
    if (!historyKeys) {
      return <p>This plot type is not supported on this page.</p>;
    }
    let sourceOptions = ['history', 'events'].map(key => ({
      key: key,
      value: key,
      text: key,
    }));
    if (!_.isNil(events) && !this.props.config.source) {
      this.props.updateConfig({...this.props.config, source: 'history'});
    }
    let keys = this.props.data.historyKeys;
    if (this.props.config.source === 'events') {
      keys = this.props.data.eventKeys;
    }
    let optionKeys = [...keys];
    if (_.indexOf(keys, 'step') === -1) {
      optionKeys.push('__index');
    }
    let options = optionKeys.map(key => {
      let text = key;
      if (key === '__index') {
        text = 'Step';
      } else if (key === '_runtime') {
        text = 'Run Time';
      }
      return {
        key: key,
        value: key,
        text: text,
      };
    });
    let xAxisOptions = _.sortBy(options, a => {
      if (a.key === 'step' || a.key === '__index') {
        return -10;
      } else if (a.key === '_runtime') {
        return -9;
      } else if (_.includes(a.key, 'epoch') || _.includes(a.key, 'Epoch')) {
        return -8;
      } else {
        return 0;
      }
    });
    return (
      <Form>
        {!_.isNil(events) && (
          <Form.Dropdown
            label="Data Source"
            placeholder="Data Source"
            fluid
            search
            selection
            options={sourceOptions}
            value={this.props.config.source}
            onChange={(e, {value}) =>
              this.props.updateConfig({...this.props.config, source: value})}
          />
        )}
        <Form.Dropdown
          label="Lines"
          placeholder="Lines"
          fluid
          multiple
          search
          selection
          options={options}
          value={this.lines}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, lines: value})}
        />
        <Form.Dropdown
          label="X-Axis Label"
          placeholder="X-Axis Label"
          fluid
          search
          selection
          options={xAxisOptions}
          value={this.props.config.xAxis}
          onChange={(e, {value}) =>
            this.props.updateConfig({...this.props.config, xAxis: value})}
        />
      </Form>
    );
    return;
  }

  renderNormal() {
    let {historyKeys, history} = this.props.data;
    if (!historyKeys) {
      return <p>This plot type is not supported on this page.</p>;
    }
    let data = this.props.data.history;
    let keys = this.props.data.historyKeys;
    if (this.props.config.source === 'events') {
      data = this.props.data.events;
      keys = this.props.data.eventKeys;
    }
    let xAxis = this.props.config.xAxis;
    if (!xAxis) {
      if (_.find(keys, o => o === 'epoch')) {
        xAxis = 'epoch';
      } else {
        xAxis = '__index';
      }
    }
    let lineNames =
      this.lines.length === 0
        ? keys
            .filter(
              lineName =>
                !_.startsWith(lineName, '_') && !(lineName == 'epoch'),
            )
            .slice(0, 10)
        : this.lines;

    let lines = lineNames
      .map((lineName, i) => {
        let lineData = data
          .map((row, j) => ({
            x: xAxis == '__index' ? j : row[xAxis],
            y: row[lineName],
          }))
          .filter(point => !_.isNil(point.x) && !_.isNil(point.y));
        return {
          title: lineName,
          color: color(i),
          data: lineData,
        };
      })
      .filter(line => line.data.length > 0);
    return (
      <LinePlot xAxis={xAxis} lines={lines} sizeKey={this.props.sizeKey} />
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
registerPanelClass(LinePlotPanel);
