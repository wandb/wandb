import React from 'react';
import DataList from '../components/DataList';

class SystemList extends React.Component {
  constructor(props) {
    super(props);
    if (this.props.data) {
      this.data = this.props.data;
    }
    this.prepData = this.prepData.bind(this);
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

  render() {
    return (
      <DataList
        data={this.data}
        prepData={this.prepData}
        formatValue={this.formatValue}
      />
    );
  }
}

export default SystemList;
