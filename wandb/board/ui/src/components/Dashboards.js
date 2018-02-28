import React, {Component} from 'react';

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
      <div className="dashboard">
        {viewId !== undefined && this.props.renderView(viewId, editMode)}
      </div>
    );
  }
}

export default Dashboards;
