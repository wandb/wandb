import React, {Component} from 'react';
import ReactGridLayout, {WidthProvider} from 'react-grid-layout';
import Panel from './Panel';
import {Button, Icon} from 'semantic-ui-react';
import _ from 'underscore';
import './DashboardView.css';

export const GRID_WIDTH = 12;
export const GRID_MARGIN = 6;

const Grid = WidthProvider(ReactGridLayout);
class DashboardView extends Component {
  static defaultProps = {
    editMode: true,
  };

  onLayoutChange = layouts => {
    layouts.forEach(layout =>
      this.props.updatePanel(parseInt(layout.i), layout),
    );
  };

  render() {
    const {data, editMode, width} = this.props;
    return (
      <div>
        {editMode && (
          <Button
            icon
            size="tiny"
            style={{position: 'absolute', right: 5, top: 5, zIndex: 102}}
            onClick={() => {
              this.props.addPanel({
                i: this.props.config.length.toString(),
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
        )}
        <Grid
          className={editMode ? 'editing' : 'display'}
          layout={this.props.config || []}
          cols={GRID_WIDTH}
          isDraggable={editMode}
          isResizable={editMode}
          margin={[GRID_MARGIN, GRID_MARGIN]}
          onLayoutChange={this.onLayoutChange}>
          {this.props.config.map((panelConfig, i) => (
            <div key={i} className="panel">
              <Panel
                editMode={this.props.editMode}
                type={panelConfig.viewType}
                size={panelConfig.size}
                config={panelConfig}
                data={data}
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
                panelIndex={this.props.id}
                updateConfig={config =>
                  this.props.updatePanel(i, {
                    ...panelConfig,
                    config: config,
                  })
                }
                removePanel={() => this.props.removePanel(i)}
              />
            </div>
          ))}
        </Grid>
      </div>
    );
  }
}

export default DashboardView;
