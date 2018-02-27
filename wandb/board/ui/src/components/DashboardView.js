import React, {Component} from 'react';
import DashLayout from './dash/DashLayout';
import DashPanel from './dash/DashLayout';
import Panel from './Panel';
import {Button, Icon} from 'semantic-ui-react';
import _ from 'underscore';
import cx from 'classnames';
import './DashboardView.css';

export const GRID_WIDTH = 9;
export const GRID_ASPECT_RATIO = 1;
export const GRID_MARGIN = 6;
export const DEFAULT_CARD_SIZE = {width: 3, height: 2};

class DashboardView extends Component {
  state = {isDragging: false};
  static defaultProps = {
    width: 0,
    editMode: true,
  };
  onDrag() {
    if (!this.state.isDragging) {
      this.setState({isDragging: true});
    }
  }
  onDragStop() {
    this.setState({isDragging: false});
  }
  //TODO: might need to intercept onMouseDownCapture
  onDashCardMouseDown = () => {};
  onLayoutChange = () => {
    console.log('Layout change');
  };

  renderGrid() {
    const {data, editMode, width} = this.props;
    const rowHeight = Math.floor(width / GRID_WIDTH / GRID_ASPECT_RATIO);
    return (
      <div>
        {editMode && (
          <Button
            onClick={() => {
              this.props.addPanel({
                i: 0,
                x: 0,
                y: 0,
                h: 2,
                w: 3,
                minSize: {
                  width: 3,
                  height: 2,
                },
              });
            }}>
            <Icon name="plus" />
          </Button>
        )}
        <DashLayout
          className={cx('DashboardGrid', {
            'Dash--editing': editMode,
            'Dash--dragging': this.state.isDragging,
          })}
          layout={this.props.config || []}
          cols={GRID_WIDTH}
          margin={GRID_MARGIN}
          rowHeight={rowHeight}
          onLayoutChange={(...args) => this.onLayoutChange(...args)}
          onDrag={(...args) => this.onDrag(...args)}
          onDragStop={(...args) => this.onDragStop(...args)}
          isEditing={editMode}>
          {this.props.config.map((panelConfig, i) => (
            <Panel
              key={i}
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
          ))}
        </DashLayout>
      </div>
    );
  }

  render() {
    const {width} = this.props;
    return (
      <div className="flex layout-centered">
        {width === 0 ? <div /> : this.renderGrid()}
      </div>
    );
  }
}

export default DashboardView;
