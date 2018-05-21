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
import {
  XAxis,
  YAxis,
  FlexibleWidthXYPlot,
  VerticalGridLines,
  HorizontalGridLines,
  ReactSeries,
  VerticalRectSeries,
  Hint,
} from 'react-vis';
import flatten from 'flat';

import {displayValue} from '../util/runhelpers.js';

class HistogramPanel extends React.Component {
  static type = 'Histogram';
  static options = {};

  static validForData(data) {
    // at least one summaryMetric needs to have a value that's an array
    return (
      data.summaryMetrics &&
      _.some(
        _.values(
          flatten(data.summaryMetrics, {
            safe: true,
          })
        ),
        val => Array.isArray(val)
      )
    );
  }

  constructor(props) {
    super(props);
  }

  renderConfig() {
    let yAxisOptions = _.keys(this.flatSummaryMetrics).map(key => ({
      key: key,
      value: key,
      text: key,
    }));

    let selectedMetrics = [];
    return (
      <Form>
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
                selectedMetrics: value,
              })
            }
          />
        </Form.Field>
      </Form>
    );
  }

  renderErrorChart(message) {
    return <div>{message}</div>;
  }

  makeHistogram(values, buckets = 10) {
    /* 
      * LB: This could be made way more efficient if people start really using it 
      */
    let min = _.min(values);
    let max = _.max(values);
    if (min == max) {
      min = min - 1;
    }
    let counts = Array(buckets)
      .fill()
      .map(e => 0);
    let binEdges = [];
    binEdges.push(min);

    for (let i = 1; i < buckets + 1; i++) {
      binEdges.push(min + i / buckets * (max - min));
      values.map(v => {
        if (v <= binEdges[i] && (i == 1 || v > binEdges[i - 1])) {
          counts[i - 1]++;
        }
      });
    }
    return {counts: counts, binEdges: binEdges};
  }

  renderNormal() {
    if (!this.props.config.selectedMetrics) {
      return this.renderErrorChart('Need to choose a metric');
    }

    let {counts, binEdges} = this.makeHistogram(
      this.flatSummaryMetrics[this.props.config.selectedMetrics]
    );
    let data = [];

    for (let i = 0; i < counts.length; i++) {
      data.push({x0: binEdges[i], x: binEdges[i + 1], y: counts[i]});
    }

    return (
      <div>
        <FlexibleWidthXYPlot
          height={this.props.currentHeight || 240}
          stackBy="y">
          <VerticalGridLines />
          <HorizontalGridLines />
          <XAxis />
          <YAxis />
          <VerticalRectSeries data={data} />
        </FlexibleWidthXYPlot>
      </div>
    );
  }

  componentDidMount() {
    if (this.container)
      this.setState({containerWidth: this.container.clientWidth});
  }

  componentWillMount() {
    this.flatSummaryMetrics = flatten(this.props.data.summaryMetrics, {
      safe: true,
    });
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
registerPanelClass(HistogramPanel);
