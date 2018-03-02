import React, {Component} from 'react';
import {Button, Icon, Menu, Tab} from 'semantic-ui-react';

class Dashboards extends Component {
  static defaultProps = {
    editMode: true,
  };

  componentDidMount() {
    //TODO: temporary hack
    if (this.props.tabs && this.props.tabs.length == 0)
      this.props.addView(this.props.viewType, 'New Dashboard', []);
  }

  render() {
    const {tabs, editMode} = this.props;
    //TODO: single dashboard view support for now
    const viewId = tabs && tabs[0];
    //TODO: Add new dashboards
    return (
      <div>
        {editMode && (
          <span style={{position: 'absolute', right: 5, top: 10, zIndex: 102}}>
            <Button
              size="tiny"
              color="green"
              content="Save"
              disabled={!this.props.isModified}
              onClick={() => {
                this.setState({editMode: false});
                this.props.updateViews(JSON.stringify(this.props.viewState));
              }}
            />
          </span>
        )}
        <div className="dashboard">
          {viewId !== undefined && this.props.renderView(viewId, editMode)}
        </div>
      </div>
    );
  }
}

export default Dashboards;
