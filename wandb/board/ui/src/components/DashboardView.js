import React, {Component} from 'react';
import ReactGridLayout, {WidthProvider} from 'react-grid-layout';
import Panel from './Panel';
import {Button, Divider, Form, Icon, Modal} from 'semantic-ui-react';
import _ from 'lodash';
import './DashboardView.css';
import EditablePanel from '../components/EditablePanel';
import * as Filter from '../util/filters';
import * as Query from '../util/query';
import * as Run from '../util/runs';

export const GRID_WIDTH = 12;
export const GRID_MARGIN = 6;
// Will be used as a default value for row height
// and for calculating panel's current height
export const ROW_HEIGHT = 150;

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
  state = {editing: null, panels: {}};
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

  renderPanel(panelConfig, i, openEdit, nightMode) {
    let query;
    // I'm so sorry...
    if (this.props.viewType != 'run') {
      query = Query.merge(this.props.pageQuery, panelConfig.query || {});
      if (
        panelConfig.viewType === 'Run History Line Plot' ||
        !panelConfig.viewType
      ) {
        // load history
        query.history = true;
        // only 10
        query.page = {
          size: 10,
        };
        // use selections in addition to filters.
        query.filters = Filter.And(query.filters, query.selections);
      }
      if (panelConfig.viewType === 'Scatter Plot' && panelConfig.config) {
        if (!panelConfig.config.xAxis || !panelConfig.config.yAxis) {
          query.disabled = true;
        } else {
          query.select = [
            Filter.serverPathKey(Run.keyFromString(panelConfig.config.xAxis)),
            Filter.serverPathKey(Run.keyFromString(panelConfig.config.yAxis)),
          ];
          if (panelConfig.config.zAxis) {
            query.select.push(
              Filter.serverPathKey(Run.keyFromString(panelConfig.config.zAxis))
            );
          }
        }
      }
      if (
        panelConfig.viewType === 'Parallel Coordinates Plot' &&
        panelConfig.config
      ) {
        if (panelConfig.config.dimensions.length === 0) {
          query.disabled = true;
        } else {
          query.select = panelConfig.config.dimensions.map(dim =>
            Filter.serverPathKey(Run.keyFromString(dim))
          );
        }
      }
    }
    return (
      <EditablePanel
        viewType={this.props.viewType}
        histQueryKey={i}
        editMode={this.props.editMode}
        nightMode={nightMode}
        openEdit={openEdit}
        noButtons={true}
        type={panelConfig.viewType}
        size={panelConfig.size}
        sizeKey={JSON.stringify(panelConfig.layout)}
        pageQuery={this.props.pageQuery}
        panelQuery={panelConfig.query}
        query={query}
        config={panelConfig.config}
        data={this.props.data}
        currentHeight={
          // LB: I'm putting a height margin of 30 in here because I think this is
          // the safest way to do it, but probably LinePlot should make the margin
          panelConfig &&
          panelConfig.layout &&
          panelConfig.layout.h * ROW_HEIGHT - 30
        }
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
      config => config.layout && validConfigLayout(config.layout)
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
      <div className="dashboard">
        {this.props.editMode && (
          <Form>
            <h5>Tab Settings</h5>
            <Form.Group>
              <Form.Input
                placeholder="Tab Name"
                value={this.props.name}
                className="tab-name"
                onChange={(e, {value}) => this.props.changeViewName(value)}
              />
              {/* hidden button so the remove button's onClick doesn't fire when the	
                    user presses enter within the Tab Name input field */}
              <Form.Button style={{display: 'none'}} />
              <Form.Button
                icon="chevron left"
                disabled={!this.props.canMoveLeft}
                onClick={() => {
                  this.props.moveViewLeft();
                }}
              />
              <Form.Button
                icon="chevron right"
                disabled={!this.props.canMoveRight}
                onClick={() => {
                  this.props.moveViewRight();
                }}
              />
              <Form.Button
                icon="x"
                content="Remove"
                onClick={() => {
                  this.props.removeView();
                }}
              />
            </Form.Group>
            <Divider />
          </Form>
        )}
        <Grid
          className={editMode ? 'editing' : 'display'}
          layout={panelConfigs.map(c => ({...c.layout}))}
          compactType="vertical"
          draggableCancel=".edit"
          cols={GRID_WIDTH}
          rowHeight={ROW_HEIGHT}
          isDraggable={true}
          isResizable={true}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          onLayoutChange={this.onLayoutChange}
          onResizeStop={(size, oldItem, newItem, placeholder, e, element) => {
            this.setState(prevState => ({
              panels: {
                ...prevState.panels,
                [newItem.i]: newItem.h * ROW_HEIGHT,
              },
            }));
          }}>
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
                      backgroundColor: 'rgb(0, 127, 175, 0.05)',
                      border: '1px dashed #666',
                      borderRadius: 0,
                      fontSize: 20,
                    }}
                    icon
                    onClick={() => {
                      let newPanelParams = {
                        layout: addPanelLayout,
                      };
                      if (this.props.viewType === 'dashboards') {
                        newPanelParams.query = {strategy: 'merge'};
                      }
                      this.props.addPanel(newPanelParams);
                      this.setState(prevState => ({
                        panels: {
                          ...prevState.panels,
                          [i]: addPanelLayout.h * ROW_HEIGHT,
                        },
                        editing: i,
                      }));
                    }}>
                    <Icon name="plus" />
                  </Button>
                </div>
              ) : (
                <div
                  key={i}
                  className="panel"
                  data-grid={{
                    ...panelConfig.layout,
                    isDraggable: true,
                    isResizable: true,
                  }}>
                  {this.renderPanel(
                    panelConfig,
                    i,
                    this.state.editing === i,
                    this.props.nightMode
                  )}
                </div>
              )
          )}
        </Grid>
      </div>
    );
  }
}

export default DashboardView;
