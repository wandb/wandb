import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import TabbedViews from '../components/TabbedViews';
import TabbedView from '../components/TabbedView';
import {
  addView,
  setActiveView,
  changeViewName,
  removeView,
  addPanel,
  removePanel,
  updatePanel,
} from '../actions/view';

class ViewModifier extends React.Component {
  renderView = (viewId, editMode) => {
    //TODO: Maybe render panel?
    const ViewComponent = this.props.viewComponent || TabbedView;
    return (
      <ViewComponent
        editMode={editMode}
        width={this.props.width}
        height={this.props.height}
        data={this.props.data}
        name={this.props.views[viewId].name}
        config={this.props.views[viewId].config}
        changeViewName={viewName =>
          this.props.changeViewName(this.props.viewType, viewId, viewName)
        }
        removeView={() => this.props.removeView(this.props.viewType, viewId)}
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
    );
  };

  render() {
    const Component = this.props.component || TabbedViews;
    return <Component renderView={this.renderView} {...this.props} />;
  }
}

function mapStateToProps(state, ownProps) {
  const browser = state.views.browser[ownProps.viewType] || {};
  return {
    viewState: state.views.browser,
    views: browser.views,
    tabs: browser.tabs,
    activeView: (state.views.other[ownProps.viewType] || {}).activeView,
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

export default connect(mapStateToProps, mapDispatchToProps)(ViewModifier);
