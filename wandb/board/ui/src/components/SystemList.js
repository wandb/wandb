import React from 'react';
import DataList from '../components/DataList';

class SystemList extends React.Component {
  constructor(props) {
    super(props);
    if (this.props.data) {
      this.data = this.props.data;
    }
  }

  formatMetric(name, metric) {
    if (name.indexOf('.temp') > -1) {
      return metric + '°';
    } else if (parseInt(metric, 10) <= 100) {
      return metric + '%';
    } else {
      return numeral(metric).format('0.0b');
    }
  }

  prepData(data) {
    var newData = {};
    Object.keys(data).map(function(key, index) {
      if (key.startsWith('system.')) {
        newData[key.replace(/^system\./, '')] = data[key];
      }
      newData[key] = data[key];
    });
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
    return <DataList data={this.data} formatValue={this.formatValue} />;
  }
}

export default SystemList;
