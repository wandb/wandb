import React from 'react';
import {List, Input, Icon, Modal, Button, Grid} from 'semantic-ui-react';
import FixedLengthString from '../components/FixedLengthString';

import {
  displayValue,
  fuzzyMatch,
  fuzzyMatchHighlight,
  truncateString,
} from '../util/runhelpers';
import _ from 'lodash';

class DataList extends React.Component {
  state = {};
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
              this._flattenInternal(newPrefix, data[key])
            )))
          : (retData[prefix.concat([key]).join('.')] = data[key])
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

  configItem(key, value, i, highlighted = false) {
    return (
      <List.Item key={'config ' + i}>
        <List.Content>
          <List.Header>
            {highlighted ? key : <FixedLengthString text={key} />}
          </List.Header>
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

  rawMode = e => {
    this.setState({format: 'raw'});
  };

  jsonMode = e => {
    this.setState({format: 'json'});
  };

  renderLongList() {
    return (
      <div>
        <Grid style={{marginBottom: 0}}>
          <Grid.Column floated="left" width={10}>
            <Input
              onChange={(e, {value}) => this.setState({filter: value})}
              icon={{name: 'search', circular: true, link: true}}
              placeholder="Search..."
              size="mini"
              className="DataListSearchBox"
            />
          </Grid.Column>
          <Grid.Column floated="right" width={3}>
            <Modal
              trigger={<Button icon="expand" size="mini" floated="right" />}>
              <Modal.Header>
                {this.props.name}
                <Button.Group floated="right">
                  <Button
                    active={this.state.format !== 'json'}
                    onClick={this.rawMode}>
                    List
                  </Button>
                  <Button
                    active={this.state.format === 'json'}
                    onClick={this.jsonMode}>
                    Json
                  </Button>
                </Button.Group>
              </Modal.Header>
              <Modal.Content>
                {this.state.format === 'json' ? (
                  JSON.stringify(this.props.data, null, '\t')
                ) : (
                  <List>
                    {_.keys(this.flatData)
                      .sort()
                      .map((key, i) =>
                        this.configItem(
                          key,
                          this.formatValue(this.flatData[key]),
                          i
                        )
                      )}
                  </List>
                )}
              </Modal.Content>
            </Modal>
          </Grid.Column>
        </Grid>
        <div className="DataListWithSearch">
          <List divided>
            {this.state.filter
              ? fuzzyMatch(Object.keys(this.flatData), this.state.filter).map(
                  (key, i) =>
                    this.configItem(
                      fuzzyMatchHighlight(key, this.state.filter),
                      this.flatData[key],
                      i,
                      true
                    )
                )
              : _.keys(this.flatData)
                  .sort()
                  .map((key, i) =>
                    this.configItem(
                      key,
                      this.formatValue(this.flatData[key]),
                      i
                    )
                  )}
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
    return <div className="DataList">{this.noData()}</div>;
  }

  render() {
    if (this.flatData && _.size(this.flatData) > 0) {
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
