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
  makeHistogram,
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
import {flatten} from '../util/flatten.js';

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

  renderNormal() {
    if (!this.props.config.selectedMetrics) {
      return this.renderErrorChart('Need to choose a metric');
    }

    let {counts, binEdges} = makeHistogram(
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
