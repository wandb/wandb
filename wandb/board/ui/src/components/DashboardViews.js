import React, {Component} from 'react';
import DashLayout from './dash/DashLayout';
import {Button, Icon} from 'semantic-ui-react';
import _ from 'underscore';
import cx from 'classnames';

export const GRID_WIDTH = 9;
export const GRID_ASPECT_RATIO = 1;
export const GRID_MARGIN = 6;
export const DEFAULT_CARD_SIZE = {width: 3, height: 2};

class DashboardViews extends Component {
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
  renderPanel() {
    return <div>Panel</div>;
  }

  componentDidMount() {
    //TODO: temporary hack
    if (this.props.tabs && this.props.tabs.length == 0)
      this.props.addView(this.props.viewType, 'New Dashboard', []);
  }

  renderGrid() {
    const {data, views, tabs, editMode, width} = this.props;
    console.log('GOT DATA', views, data);
    //TODO: single dashboard view support for now
    const viewId = tabs && tabs[0];
    const rowHeight = Math.floor(width / GRID_WIDTH / GRID_ASPECT_RATIO);
    return (
      <div>
        {editMode && (
          <Button
            onClick={() => {
              this.props.addPanel(this.props.viewType, viewId || 0, {
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
          layout={(views[viewId] || {}).config || []}
          cols={GRID_WIDTH}
          margin={GRID_MARGIN}
          rowHeight={rowHeight}
          onLayoutChange={(...args) => this.onLayoutChange(...args)}
          onDrag={(...args) => this.onDrag(...args)}
          onDragStop={(...args) => this.onDragStop(...args)}
          isEditing={editMode}>
          {viewId !== undefined && this.props.renderView(viewId, editMode)}
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

export default DashboardViews;
