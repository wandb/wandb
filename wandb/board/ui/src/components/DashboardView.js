import React, {Component} from 'react';
import ReactGridLayout, {WidthProvider} from 'react-grid-layout';
import Panel from './Panel';
import {Button, Icon, Modal} from 'semantic-ui-react';
import _ from 'lodash';
import './DashboardView.css';
import * as Query from '../util/query';

export const GRID_WIDTH = 12;
export const GRID_MARGIN = 6;

function findNextPanelLoc(layouts, gridWidth, panelWidth) {
  let columnBottoms = new Array(gridWidth).fill(0);
  for (let panel of layouts) {
    let panelBottom = panel.y + panel.h;
    for (let x = panel.x; x < panel.x + panel.w; x++) {
      columnBottoms[x] = Math.max(columnBottoms[x], panelBottom);
    }
  }
  let candidates = [];
  for (let x = 0; x < gridWidth - panelWidth + 1; x++) {
    candidates.push(_.max(columnBottoms.slice(x, x + panelWidth)));
  }
  // argmin
  let min = candidates[0];
  let argmin = 0;
  for (var x = 1; x < candidates.length; x++) {
    if (candidates[x] < min) {
      min = candidates[x];
      argmin = x;
    }
  }
  let result = {x: argmin, y: min};
  return result;
}

function convertTabbedPanels(panelConfigs) {
  if (panelConfigs.length > 0 && _.isNil(panelConfigs[0].layout)) {
    // This is an old set of configs. Convert it!
    let curX = 0;
    let curY = 0;
    let newConfigs = [];
    for (var panelConfig of panelConfigs) {
      let width = (panelConfig.size && panelConfig.size.width) === 16 ? 12 : 6;
      if (panelConfig.viewType === 'Parallel Coordinates Plot') {
        width = 16;
      }
      if (curX + width > GRID_WIDTH) {
        curX = 0;
        curY += 2;
      }
      let newConfig = {
        ...panelConfig,
        layout: {x: curX, y: curY, w: width, h: 2},
      };
      delete newConfig.size;
      curX += width;
      newConfigs.push(newConfig);
    }
    panelConfigs = newConfigs;
  }
  return panelConfigs;
}

function validConfigLayout(layout) {
  let requiredKeys = ['x', 'y', 'w', 'h'];
  let keys = _.keys(layout);
  return (
    _.intersection(keys, requiredKeys).length === requiredKeys.length &&
    _.union(keys, requiredKeys).length === requiredKeys.length
  );
}

let gridKey = 1;

const Grid = WidthProvider(ReactGridLayout);
class DashboardView extends Component {
  state = {editing: null};
  static defaultProps = {
    editMode: true,
  };

  constructor(props) {
    super(props);
    this.renderCounter = 0;
  }

  onLayoutChange = layouts => {
    layouts.forEach(layout => {
      if (layout.i === 'addPanel') {
        return;
      }
      let i = parseInt(layout.i);
      let newLayout = {
        x: layout.x,
        y: layout.y,
        w: layout.w,
        h: layout.h,
      };
      if (!_.isEqual(this.props.config[i].layout, newLayout)) {
        this.props.updatePanel(i, {
          ...this.props.config[i],
          layout: newLayout,
        });
      }
    });
  };

  renderPanel(panelConfig, i, edit) {
    let query = Query.merge(this.props.pageQuery, panelConfig.query || {});
    return (
      <Panel
        viewType={this.props.viewType}
        histQueryKey={i}
        editMode={edit}
        noButtons={true}
        type={panelConfig.viewType}
        size={panelConfig.size}
        sizeKey={JSON.stringify(panelConfig.layout)}
        pageQuery={this.props.pageQuery}
        panelQuery={panelConfig.query}
        query={query}
        config={panelConfig.config}
        data={this.props.data}
        updateType={newType =>
          this.props.updatePanel(i, {
            ...panelConfig,
            viewType: newType,
          })
        }
        updateSize={newSize =>
          this.props.updatePanel(i, {
            ...panelConfig,
            size: newSize,
          })
        }
        updateQuery={newQuery =>
          this.props.updatePanel(i, {...panelConfig, query: newQuery})
        }
        panelIndex={this.props.id}
        updateConfig={config =>
          this.props.updatePanel(i, {
            ...panelConfig,
            config: config,
          })
        }
        removePanel={() => this.props.removePanel(i)}
      />
    );
  }

  render() {
    const {editMode, width} = this.props;

    // Configs must have a layout key
    let panelConfigs = convertTabbedPanels(this.props.config).filter(
      config => config.layout && validConfigLayout(config.layout),
    );
    if (panelConfigs.length !== this.props.config.length) {
      // If we found invalid panels, update the browser state so on next save
      // we'll only save the valid set.
      // this.props.updateView(panelConfigs);
    }
    let allPanelConfigs = [...panelConfigs];
    let addPanelLayout = null;
    if (editMode) {
      allPanelConfigs.push('addButton');
      addPanelLayout = {
        ...findNextPanelLoc(panelConfigs.map(c => c.layout), GRID_WIDTH, 6),
        w: 6,
        h: 2,
      };
    }

    return (
      <div>
        <Grid
          className={editMode ? 'editing' : 'display'}
          layout={panelConfigs.map(c => c.layout)}
          compactType="vertical"
          draggableCancel=".edit"
          cols={GRID_WIDTH}
          isDraggable={editMode}
          isResizable={editMode}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          onLayoutChange={this.onLayoutChange}>
          {allPanelConfigs.map(
            (panelConfig, i) =>
              panelConfig === 'addButton' ? (
                <div
                  key="addPanel"
                  data-grid={{
                    ...addPanelLayout,
                    isDraggable: false,
                    isResizable: false,
                  }}>
                  <Button
                    style={{
                      width: '100%',
                      height: '100%',
                      backgroundColor: '#f8fbf8',
                      border: '3px dashed #666',
                      fontSize: 20,
                    }}
                    icon
                    size="small"
                    onClick={() => {
                      let newPanelParams = {
                        layout: addPanelLayout,
                      };
                      if (this.props.viewType === 'dashboards') {
                        newPanelParams.query = {strategy: 'merge'};
                      }
                      this.props.addPanel(newPanelParams);
                    }}>
                    <Icon name="plus" />
                  </Button>
                </div>
              ) : (
                <div
                  key={i}
                  className="panel"
                  data-grid={{...panelConfig.layout}}>
                  {editMode && (
                    <Modal
                      open={this.state.editing === i}
                      dimmer={false}
                      trigger={
                        <Icon
                          link
                          name="edit"
                          onClick={() => this.setState({editing: i})}
                        />
                      }>
                      <Modal.Header>Edit Panel</Modal.Header>
                      <Modal.Content style={{padding: 16}}>
                        {this.renderPanel(panelConfig, i, true)}
                      </Modal.Content>
                      <Modal.Actions>
                        <Button
                          floated="left"
                          negative
                          icon="trash"
                          onClick={() => {
                            this.props.removePanel(i);
                            this.setState({editing: null});
                          }}
                        />
                        <Button onClick={() => this.setState({editing: null})}>
                          OK
                        </Button>
                      </Modal.Actions>
                    </Modal>
                  )}

                  {this.renderPanel(panelConfig, i, false)}
                </div>
              ),
          )}
        </Grid>
      </div>
    );
  }
}

export default DashboardView;
