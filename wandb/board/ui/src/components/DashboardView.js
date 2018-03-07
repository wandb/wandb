import React, {Component} from 'react';
import ReactGridLayout, {WidthProvider} from 'react-grid-layout';
import Panel from './Panel';
import {Button, Icon, Modal} from 'semantic-ui-react';
import _ from 'underscore';
import './DashboardView.css';
import * as Query from '../util/query';

export const GRID_WIDTH = 12;
export const GRID_MARGIN = 6;

function validConfigLayout(layout) {
  let requiredKeys = ['x', 'y', 'w', 'h'];
  let keys = _.keys(layout);
  return (
    _.intersection(keys, requiredKeys).length === requiredKeys.length &&
    _.union(keys, requiredKeys).length === requiredKeys.length
  );
}

const Grid = WidthProvider(ReactGridLayout);
class DashboardView extends Component {
  state = {editing: null};
  static defaultProps = {
    editMode: true,
  };

  onLayoutChange = layouts => {
    layouts.forEach(layout => {
      let i = parseInt(layout.i);
      this.props.updatePanel(i, {
        ...this.props.config[i],
        layout: {
          x: layout.x,
          y: layout.y,
          w: layout.w,
          h: layout.h,
        },
      });
    });
  };

  renderPanel(panelConfig, i, edit) {
    let query = Query.merge(this.props.pageQuery, panelConfig.query || {});
    return (
      <Panel
        histQueryKey={i}
        editMode={edit}
        noCard={edit}
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
    let panelConfigs = this.props.config.filter(
      config => config.layout && validConfigLayout(config.layout),
    );
    if (panelConfigs.length !== this.props.config.length) {
      // If we found invalid panels, update the browser state so on next save
      // we'll only save the valid set.
      this.props.updateView(panelConfigs);
    }

    return (
      <div>
        {editMode && (
          <span style={{position: 'absolute', right: 75, top: 10, zIndex: 102}}>
            <Button
              icon
              size="tiny"
              onClick={() => {
                this.props.addPanel({
                  layout: {
                    x: 0,
                    y: 0,
                    w: 6,
                    h: 2,
                  },
                  query: {strategy: 'merge'},
                });
              }}>
              <Icon name="plus" />
            </Button>
          </span>
        )}
        <Grid
          className={editMode ? 'editing' : 'display'}
          draggableCancel=".edit"
          cols={GRID_WIDTH}
          isDraggable={editMode}
          isResizable={editMode}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          onLayoutChange={this.onLayoutChange}>
          {panelConfigs.map((panelConfig, i) => (
            <div key={i} className="panel" data-grid={{...panelConfig.layout}}>
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
          ))}
        </Grid>
      </div>
    );
  }
}

export default DashboardView;
