import React from 'react';
import _ from 'lodash';
import {Button, Card, Dropdown, Grid, Icon, Segment} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';
import QueryEditor from '../components/QueryEditor';
import {filterRuns, sortRuns} from '../util/runhelpers.js';
import withRunsDataLoader from '../containers/RunsDataLoader';
import ContentLoader from 'react-content-loader';

import './PanelRunsLinePlot';
import './PanelLinePlot';
import './PanelImages';
import './PanelScatterPlot';
import './PanelParallelCoord';

export default class Panel extends React.Component {
  state = {configMode: false, showQuery: false};
  static loading = (
    <Segment basic style={{minHeight: 260}}>
      <ContentLoader height={85} />
    </Segment>
  );

  renderPanelType(
    PanelType,
    configMode,
    config,
    data,
    sizeKey,
    panelQuery,
    currentHeight,
  ) {
    if (!data) {
      return Panel.loading;
    }
    return (
      <div style={{clear: 'both'}}>
        <PanelType
          configMode={configMode}
          config={config}
          updateConfig={this.props.updateConfig}
          sizeKey={sizeKey}
          panelQuery={panelQuery}
          currentHeight={currentHeight}
          data={data}
        />
      </div>
    );
  }

  render() {
    let {type, size, config, data} = this.props;
    let panel, PanelType, configMode, options, sizeKey;
    if (!data) {
      panel = Panel.loading;
    } else {
      options = _.keys(panelClasses)
        .filter(type => panelClasses[type].validForData(data))
        .map(type => ({text: type, value: type}));
      if (options.length === 0) {
        panel = Panel.loading;
      } else {
        type = type || options[0].value;
        config = config || {};
        PanelType = panelClasses[type] || panelClasses[_.keys(panelClasses)[0]];
        configMode = this.props.editMode;
        size = PanelType.options.width
          ? {width: PanelType.options.width}
          : size || {width: 8};
        sizeKey = size.width;
      }
    }

    if (!panel && this.props.editMode) {
      panel = (
        <div>
          {!this.props.noButtons && (
            <Button.Group basic floated="right">
              {/*
                <Button
                  icon="settings"
                  circular
                  size="tiny"
                  onClick={() =>
                    this.setState({configMode: !this.state.configMode})}
                  />*/}
              {!PanelType.options.width && (
                <Button
                  icon={size.width === 8 ? 'expand' : 'compress'}
                  circular
                  size="tiny"
                  onClick={() => {
                    let newWidth = size.width === 8 ? 16 : 8;
                    this.props.updateSize({width: newWidth});
                  }}
                />
              )}
              <Button
                icon="close"
                circular
                size="tiny"
                onClick={() => this.props.removePanel()}
              />
            </Button.Group>
          )}
          {configMode && (
            <Dropdown
              placeholder="Panel Type"
              selection
              options={options}
              value={type}
              onChange={(e, {value}) => {
                console.log('onchange', value);
                this.props.updateType(value);
              }}
              style={{marginBottom: 12, zIndex: 21}}
            />
          )}
          {configMode &&
            (this.props.viewType === 'dashboards' ||
              this.props.viewType === 'runs') && (
              <QueryEditor
                pageQuery={this.props.pageQuery}
                panelQuery={this.props.panelQuery}
                allowProjectChange={this.props.viewType === 'dashboards'}
                setQuery={this.props.updateQuery}
                runs={this.props.data.base}
                keySuggestions={this.props.data.keys}
              />
            )}
          {this.renderPanelType(PanelType, configMode, config, data, sizeKey)}
        </div>
      );
    } else if (!panel) {
      panel = this.renderPanelType(
        PanelType,
        configMode,
        config,
        data,
        sizeKey,
        this.props.panelQuery,
        this.props.currentHeight,
      );
    }
    return <div className={this.props.className}>{panel}</div>;
  }
}
