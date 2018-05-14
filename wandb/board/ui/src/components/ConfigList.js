import React from 'react';
import DataList from '../components/DataList';
import {Icon} from 'semantic-ui-react';

class ConfigList extends React.Component {
  constructor(props) {
    super(props);
    if (this.props.data) {
      this.data = this.props.data;
    }
    this.noData = this.noData.bind(this);
  }

  prepData(data) {
    return this.removeValues(data);
  }

  noData() {
    return (
      <div>
        <p>No configuration saved for this run.</p>
        <p>
          {' '}
          Check the{' '}
          <a href="https://docs.wandb.com/docs/configs.html">
            configuration documentation
          </a>{' '}
          for more information.
        </p>
      </div>
    );
  }

  _setup(props) {
    if (props.data && Object.keys(props.data).length > 0) {
      this.data = this.prepData(props.data);
    }
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillReceiveProps(nextProps) {
    this._setup(nextProps);
  }

  removeValues(data) {
    Object.keys(data).map(
      (key, i) => (data[key] = data[key].value || data[key])
    );
    return data;
  }

  render() {
    return (
      <DataList name="Configuration" data={this.data} noData={this.noData} />
    );
  }
}

export default ConfigList;
