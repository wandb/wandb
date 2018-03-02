import React, {Component} from 'react';
import ReactGridLayout, {WidthProvider} from 'react-grid-layout';
import Panel from './Panel';
import {Button, Icon, Modal} from 'semantic-ui-react';
import _ from 'underscore';
import './DashboardView.css';
import * as Query from '../util/query';

export const GRID_WIDTH = 12;
export const GRID_MARGIN = 6;

const Grid = WidthProvider(ReactGridLayout);
class DashboardView extends Component {
  static defaultProps = {
    editMode: true,
  };

  onLayoutChange = layouts => {
    layouts.forEach(layout => {
      let i = parseInt(layout.i);
      this.props.updatePanel(i, {...this.props.config[i], ...layout});
    });
  };

  renderPanel(panelConfig, i, edit) {
    let query = Query.merge(this.props.pageQuery, panelConfig.query || {});
    return (
      <Panel
        histQueryKey={i}
        editMode={edit}
        type={panelConfig.viewType}
        size={panelConfig.size}
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
    return (
      <div>
        {editMode && (
          <span style={{position: 'absolute', right: 5, top: 5, zIndex: 102}}>
            <Button
              icon
              size="tiny"
              onClick={() => {
                this.props.addPanel({
                  i: 0,
                  x: 0,
                  y: 0,
                  w: 3,
                  h: 2,
                  minW: 3,
                  minH: 1,
                });
              }}>
              <Icon name="plus" />
            </Button>
          </span>
        )}
        <Grid
          className={editMode ? 'editing' : 'display'}
          draggableCancel=".edit"
          layout={this.props.config || []}
          verticalCompact={false}
          cols={GRID_WIDTH}
          isDraggable={editMode}
          isResizable={editMode}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          onLayoutChange={this.onLayoutChange}>
          {this.props.config.map((panelConfig, i) => (
            <div key={i} className="panel">
              <Modal
                dimmer={false}
                trigger={<Icon link name="edit" />}
                header="Edit panel"
                content={
                  <div style={{padding: 10}}>
                    {this.renderPanel(panelConfig, i, true)}
                  </div>
                }
                actions={[
                  'Cancel',
                  {key: 'save', content: 'Save', positive: true},
                ]}
              />
              {this.renderPanel(panelConfig, i)}
            </div>
          ))}
        </Grid>
      </div>
    );
  }
}

export default DashboardView;
