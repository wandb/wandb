import React from 'react';
import {List, Input, Icon} from 'semantic-ui-react';
import {
  displayValue,
  fuzzyMatch,
  fuzzyMatchHighlight,
} from '../util/runhelpers';
import _ from 'lodash';

class DataList extends React.Component {
  constructor(props) {
    super(props);
    this.noData = this.noDataDefault;
    this.formatValue = this.formatValueDefault;
  }

  _setup(props) {
    this.state = {};
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
      <List.Item key={'config ' + i}>
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

  renderLongList() {
    console.log('Rendering Long List');
    return (
      <div>
        <Input
          onChange={(e, {value}) => this.setState({filter: value})}
          icon={{name: 'search', circular: true, link: true}}
          placeholder="Search..."
          size="mini"
        />
        <div className="DataListWithSearch">
          <List divided>
            {this.state.filter
              ? fuzzyMatch(Object.keys(this.flatData), this.state.filter)
                  .sort()
                  .map((key, i) =>
                    this.configItem(
                      fuzzyMatchHighlight(key, this.state.filter),
                      this.flatData[key],
                      i,
                    ),
                  )
              : _.keys(this.flatData)
                  .sort()
                  .map((key, i) => this.configItem(key, this.flatData[key], i))}
          </List>
        </div>
      </div>
    );
  }

  renderShortList() {
    return (
      <div className="DataList">
        <List divided>
          {_.keys(this.flatData)
            .sort()
            .map((key, i) => this.configItem(key, this.flatData[key], i))}
        </List>
      </div>
    );
  }

  renderNoData() {
    return <div className="DataList">{this.noData}</div>;
  }

  render() {
    if (this.flatData) {
      console.log('Len', _.size(this.flatData));
      if (_.size(this.flatData) > 10) {
        return this.renderLongList();
      } else {
        return this.renderShortList();
      }
    } else {
      return this.renderNoData();
    }
  }
}

export default DataList;
