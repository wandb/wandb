import React from 'react';
import _ from 'lodash';
import {Button, Card, Dropdown, Grid} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';

import './PanelRunsLinePlot';
import './PanelLinePlot';
import './PanelImages';
import './PanelScatterPlot';
import './PanelParallelCoord';

class Panel extends React.Component {
  state = {configMode: false};

  renderPanelType(PanelType, configMode, config, data, sizeKey) {
    if (!data) {
      return <p>Views unavailable until data is ready</p>;
    }
    return (
      <div style={{clear: 'both'}}>
        <PanelType
          configMode={configMode}
          config={config}
          updateConfig={this.props.updateConfig}
          sizeKey={sizeKey}
          data={data}
        />
      </div>
    );
  }

  componentDidMount() {
    // This happens when a new panel is added, go straight to configMode
    if (!this.props.config) {
      this.setState({configMode: true});
    }
  }

  render() {
    let {type, size, config, data} = this.props;
    let panel, PanelType, configMode, options, sizeKey;
    if (!data) {
      panel = <p>Views unavailable until data is ready.</p>;
    } else {
      options = _.keys(panelClasses)
        .filter(type => panelClasses[type].validForData(data))
        .map(type => ({text: type, value: type}));
      if (options.length === 0) {
        panel = <p>Views unavailable until data is ready.</p>;
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
        <Grid.Column width={size.width}>
          <Card fluid>
            <Card.Content>
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
              {configMode && (
                <Dropdown
                  placeholder="Panel Type"
                  selection
                  options={options}
                  value={type}
                  onChange={(e, {value}) => this.props.updateType(value)}
                  style={{marginBottom: 12}}
                />
              )}
              {this.renderPanelType(
                PanelType,
                configMode,
                config,
                data,
                sizeKey,
              )}
            </Card.Content>
          </Card>
        </Grid.Column>
      );
    } else if (!panel) {
      panel = (
        <Grid.Column width={size.width}>
          {this.renderPanelType(PanelType, configMode, config, data, sizeKey)}
        </Grid.Column>
      );
    }
    return (
      <div style={this.props.style} className={this.props.className}>
        {panel}
      </div>
    );
  }
}

export default Panel;
