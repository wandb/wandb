import React from 'react';
import DataList from '../components/DataList';

class ConfigList extends React.Component {
  constructor(props) {
    super(props);
    if (this.props.data) {
      this.data = this.props.data;
    }
    this.noData = this.noData.bind(this);
    this.prepData = this.prepData.bind(this);
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
          <a href="http://docs.wandb.com/#configurations">
            configuration documentation
          </a>{' '}
          for more information.
        </p>
      </div>
    );
  }

  removeValues(data) {
    Object.keys(data).map(
      (key, i) => (data[key] = data[key].value || data[key]),
    );
    return data;
  }

  render() {
    return (
      <DataList
        data={this.data}
        prepData={this.prepData}
        noData={this.noData}
      />
    );
  }
}

export default ConfigList;
