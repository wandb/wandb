import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Button, Icon, Menu, Tab, Segment, Message} from 'semantic-ui-react';
import View from '../components/View';
import {
  addView,
  setActiveView,
  changeViewName,
  removeView,
  addPanel,
  removePanel,
  updatePanel,
} from '../actions/view';

class Views extends React.Component {
  state = {editMode: false};

  render() {
    let panes = this.props.tabs.map(viewId => ({
      menuItem: {
        key: viewId,
        content: <span>{this.props.views[viewId].name + ' '}</span>,
      },
      render: () => (
        <Tab.Pane>
          {this.props.loader && !this.props.data.history ? (
            <Segment loading basic style={{minHeight: 260}} />
          ) : !this.props.loader || this.props.data.history.length !== 0 ? (
            <View
              editMode={this.state.editMode}
              data={this.props.data}
              name={this.props.views[viewId].name}
              config={this.props.views[viewId].config}
              changeViewName={viewName =>
                this.props.changeViewName(this.props.viewType, viewId, viewName)
              }
              removeView={() =>
                this.props.removeView(this.props.viewType, viewId)
              }
              updatePanel={(panelIndex, panelConfig) =>
                this.props.updatePanel(
                  this.props.viewType,
                  viewId,
                  panelIndex,
                  panelConfig,
                )
              }
              addPanel={panel =>
                this.props.addPanel(this.props.viewType, viewId, panel)
              }
              removePanel={panelIndex =>
                this.props.removePanel(this.props.viewType, viewId, panelIndex)
              }
            />
          ) : (
            <Message>No data available</Message>
          )}
        </Tab.Pane>
      ),
    }));
    if (this.state.editMode) {
      panes.push({
        menuItem: (
          <Menu.Item
            key="add"
            onClick={() =>
              this.props.addView(this.props.viewType, 'New View', [])
            }>
            <Icon name="plus" />
          </Menu.Item>
        ),
      });
    }
    let activeIndex = 0;
    if (!_.isNil(this.props.activeView)) {
      activeIndex = _.indexOf(this.props.tabs, this.props.activeView);
      if (activeIndex === -1) {
        activeIndex = 0;
      }
    }
    return (
      <div>
        {this.state.editMode && (
          <Button
            color="green"
            floated="right"
            content="Save Changes"
            disabled={!this.props.isModified}
            onClick={() => {
              this.setState({editMode: false});
              this.props.updateViews(JSON.stringify(this.props.viewState));
            }}
          />
        )}
        <Button
          content={this.state.editMode ? 'View Charts' : 'Edit Charts'}
          floated="right"
          icon={this.state.editMode ? 'unhide' : 'configure'}
          onClick={() => this.setState({editMode: !this.state.editMode})}
        />
        <Tab
          panes={panes}
          activeIndex={activeIndex}
          onTabChange={(event, {activeIndex}) => {
            this.props.setActiveView(
              this.props.viewType,
              this.props.tabs[activeIndex] || activeIndex,
            );
          }}
        />
      </div>
    );
  }
}

function mapStateToProps(state, ownProps) {
  return {
    viewState: state.views.browser,
    views: state.views.browser[ownProps.viewType].views,
    tabs: state.views.browser[ownProps.viewType].tabs,
    activeView: state.views.other[ownProps.viewType].activeView,
    isModified: !_.isEqual(
      state.views.server[ownProps.viewType],
      state.views.browser[ownProps.viewType],
    ),
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {
      addView,
      setActiveView,
      changeViewName,
      removeView,
      addPanel,
      removePanel,
      updatePanel,
    },
    dispatch,
  );
};

export default connect(mapStateToProps, mapDispatchToProps)(Views);
