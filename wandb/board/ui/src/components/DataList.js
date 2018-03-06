import React from 'react';
import {List} from 'semantic-ui-react';
import {displayValue} from '../util/runhelpers';

class DataList extends React.Component {
  constructor(props) {
    super(props);
    if (props.noData) {
      this.noData = props.noData;
    } else {
      this.noData = this.noDataDefault;
    }
    if (props.prepData) {
      this.prepData = props.prepData;
    } else {
      this.prepData = this.prepDataDefault;
    }
    if (props.formatValue) {
      this.formatValue = props.formatValue;
    } else {
      this.formatValue = this.formatValueDefault;
    }

    if (props.data && Object.keys(props.data).length > 0) {
      this.preppedData = this.prepData(props.data);
      this.flatData = this.flatten(this.preppedData);
    }
  }

  isDict(v) {
    return (
      typeof v === 'object' &&
      v !== null &&
      !(v instanceof Array) &&
      !(v instanceof Date)
    );
  }

  flattenInternal(prefix, data) {
    var prefixStr = prefix.join('.');
    var retData = {};
    var newPrefix;
    Object.keys(data).map(
      (key, i) =>
        this.isDict(data[key])
          ? ((newPrefix = prefix.concat([key])),
            (retData = Object.assign(
              retData,
              this.flattenInternal(newPrefix, data[key]),
            )))
          : (retData[prefix.concat([key]).join('.')] = data[key]),
    );

    return retData;
  }

  flatten(data) {
    var flatData = this.flattenInternal([], data);
    return flatData;
  }

  prepDataDefault(data) {
    return data;
  }

  configItem(key, value, i) {
    return (
      <List.Item key={'config ' + key + i}>
        <List.Content>
          <List.Header>{key}</List.Header>
          <List.Description>{'' + this.formatValue(value)}</List.Description>
        </List.Content>
      </List.Item>
    );
  }

  noDataDefault() {
    return <p>No data</p>;
  }

  formatValueDefault(value) {
    return displayValue(value);
  }

  render() {
    return (
      <div>
        {this.flatData ? (
          <List divided size="small">
            {Object.keys(this.flatData)
              .sort()
              .map((key, i) => this.configItem(key, this.flatData[key], i))}
          </List>
        ) : (
          this.noData()
        )}
      </div>
    );
  }
}

export default DataList;
