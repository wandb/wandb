import React from 'react';
import {List} from 'semantic-ui-react';
import {displayValue} from '../util/runhelpers';

class DataList extends React.Component {
  constructor(props) {
    super(props);
    this.noData = this.noDataDefault;
    this.formatValue = this.formatValueDefault;
  }

  _setup(props) {
    if (props.noData) {
      this.noData = props.noData;
    }
    if (props.formatValue) {
      this.formatValue = props.formatValue;
    }

    if (props.data && Object.keys(props.data).length > 0) {
      this.flatData = this._flatten(props.data);
    }
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillReceiveProps(nextProps) {
    this._setup(nextProps);
  }

  isDict(v) {
    return (
      typeof v === 'object' &&
      v !== null &&
      !(v instanceof Array) &&
      !(v instanceof Date)
    );
  }

  _flattenInternal(prefix, data) {
    var prefixStr = prefix.join('.');
    var retData = {};
    var newPrefix;
    Object.keys(data).map(
      (key, i) =>
        this.isDict(data[key])
          ? ((newPrefix = prefix.concat([key])),
            (retData = Object.assign(
              retData,
              this._flattenInternal(newPrefix, data[key]),
            )))
          : (retData[prefix.concat([key]).join('.')] = data[key]),
    );

    return retData;
  }

  _flatten(data) {
    var flatData = this._flattenInternal([], data);
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
