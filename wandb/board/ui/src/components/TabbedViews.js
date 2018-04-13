import React from 'react';
import _ from 'lodash';
import PropTypes from 'prop-types';
import {Popup, Button, Icon, Menu, Tab} from 'semantic-ui-react';

class TabbedViews extends React.Component {
  state = {editMode: false, nightMode: false};

  static propTypes = {
    renderView: PropTypes.func.isRequired,
  };

  componentWillUnmount() {
    console.log('Unmounting night mode');
    if (this.state.nightMode) {
      this.setNightMode(false);
    }
  }

  setNightMode(nightMode) {
    this.setState({nightMode: nightMode});
    if (nightMode) {
      document.body.style.background = '#55565B';
      document.body.style.color = '#fff';
      document.body.className = 'nightMode';
    } else {
      document.body.style.background = '#fff';
      document.body.style.color = '#000';
      document.body.className = 'dayMode';
    }
  }

  render() {
    let panes = this.props.tabs.map((viewId, i) => ({
      menuItem: {
        key: viewId,
        content: <span>{this.props.views[viewId].name + ' '}</span>,
      },
      render: () => (
        <Tab.Pane as="div">
          {this.props.renderView(
            viewId,
            this.state.editMode,
            i !== 0,
            i !== this.props.tabs.length - 1
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
            color="yellow"
            floated="right"
            content="Save Changes"
            disabled={!this.props.isModified}
            onClick={() => {
              this.setState({editMode: false});
              this.props.updateViews(JSON.stringify(this.props.viewState));
            }}
          />
        )}
        {this.props.viewType !== 'dashboards' && (
          <Button
            content={this.state.editMode ? 'View Charts' : 'Edit Charts'}
            floated="right"
            icon={this.state.editMode ? 'unhide' : 'configure'}
            onClick={() => this.setState({editMode: !this.state.editMode})}
          />
        )}

        {!this.props.fullScreen &&
          (this.props.viewType === 'dashboards' && (
            <Popup
              trigger={
                <Button
                  floated="right"
                  icon={this.state.editMode ? 'unhide' : 'configure'}
                  onClick={() =>
                    this.setState({editMode: !this.state.editMode})
                  }
                />
              }
              content="Edit Charts"
            />
          ))}
        {this.props.viewType === 'dashboards' &&
          !this.props.fullScreen && (
            <Popup
              trigger={
                <Button
                  floated="right"
                  icon="window maximize"
                  onClick={() => this.props.setFullScreen(true)}
                />
              }
              content="Full Screen"
            />
          )}
        {this.props.viewType === 'dashboards' &&
          !this.props.fullScreen && (
            <Popup
              trigger={
                <Button
                  floated="right"
                  icon="print"
                  onClick={() => window.print()}
                />
              }
              content="Print"
            />
          )}
        {this.props.viewType === 'dashboards' &&
          !this.props.fullScreen && (
            <Popup
              trigger={
                <Button
                  floated="right"
                  icon="moon"
                  onClick={() => this.setNightMode(!this.state.nightMode)}
                />
              }
              content="Night Mode"
            />
          )}
        <Tab
          className={this.state.nightMode ? 'nightMode' : 'dayMode'}
          panes={panes}
          menu={{secondary: true, pointing: true}}
          activeIndex={activeIndex}
          onTabChange={(event, {activeIndex}) => {
            this.props.setActiveView(
              this.props.viewType,
              this.props.tabs[activeIndex]
            );
          }}
        />
      </div>
    );
  }
}

export default TabbedViews;
