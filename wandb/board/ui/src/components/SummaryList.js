import React from 'react';
import DataList from '../components/DataList';

class SummaryList extends React.Component {
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
        <p>No summary saved for this run.</p>
        <p>
          {' '}
          Check the{' '}
          <a href="http://docs.wandb.com/#summary">summary documentation</a> for
          more information.
        </p>
      </div>
    );
  }

  removeValues(data) {
    var newData = {};
    Object.keys(data)
      .filter(key => key.slice(0, 1) !== '_')
      .map((key, i) => (newData[key] = data[key]));
    return newData;
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

  render() {
    return <DataList data={this.data} noData={this.noData} />;
  }
}

export default SummaryList;
