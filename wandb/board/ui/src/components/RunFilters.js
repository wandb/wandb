import React from 'react';
import {Button, Dropdown, Form, Popup, Select} from 'semantic-ui-react';
import {
  addFilter,
  deleteFilter,
  editFilter,
  setFilterComponent,
} from '../actions/run';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import update from 'immutability-helper';
import _ from 'lodash';
import RunKeySelector from '../components/RunKeySelector';
import * as Run from '../util/runhelpers';

import './RunFilters.css';

class RunFilterEditor extends React.Component {
  componentWillMount() {
    this.keyValueCounts = Run.setupKeyValueCounts(
      this.props.runs,
      this.props.keys,
      this.props.otherFilters,
    );
    this.setupValueSuggestions(this.props);
  }

  displayValue(value) {
    if (this.props.filterKey.section === 'tags') {
      return value === 'true' ? 'Set' : 'Unset';
    } else {
      return Run.displayValue(value);
    }
  }

  setupValueSuggestions(props) {
    let valueCounts = this.keyValueCounts[
      Run.displayFilterKey(this.props.filterKey)
    ];
    if (valueCounts) {
      if (this.props.filterKey.section === 'tags') {
        // We want true before false
        valueCounts = [...valueCounts].reverse();
      } else if (props.op === '=') {
        valueCounts = [{value: '*'}, ...valueCounts];
      }
      this.valueSuggestions = valueCounts.map(({value, count}) => {
        let displayVal = this.displayValue(value);
        return {
          key: value,
          text: displayVal,
          content: (
            <span
              style={{
                display: 'inline-block',
                width: '100%',
              }}
              key={{value}}>
              <span
                style={{
                  display: 'inline-block',
                  whitespace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                {displayVal}
              </span>
              {!_.isNil(count) && (
                <span
                  style={{
                    width: 60,
                    fontStyle: 'italic',
                    display: 'inline-block',
                    float: 'right',
                    whitespace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                  ({count} {count === 1 ? 'run' : 'runs'})
                </span>
              )}
            </span>
          ),
          value: value,
        };
      });
      if (!this.props.value && this.valueSuggestions.length > 0) {
        this.props.setFilterComponent(
          this.props.kind,
          this.props.id,
          'value',
          this.valueSuggestions[0].value,
        );
      }
    } else {
      this.valueSuggestions = [];
    }
  }

  componentWillReceiveProps(nextProps) {
    this.setupValueSuggestions(nextProps);
  }

  render() {
    let operators = ['=', '!=', '>=', '<='].map(op => ({text: op, value: op}));
    console.log('RunFilters', this.keyValueCounts);
    return (
      <Form>
        <Form.Field>
          <RunKeySelector
            keys={_.map(
              this.keyValueCounts,
              (valueCounts, key) =>
                _.keys(valueCounts).length > 1 ? key : null,
            ).filter(o => o)}
            storedKey={Run.displayFilterKey(this.props.filterKey)}
            onValidSelection={filterKey => {
              this.props.setFilterComponent(
                this.props.kind,
                this.props.id,
                'key',
                Run.filterKeyFromString(filterKey),
              );
            }}
          />
        </Form.Field>
        {this.props.filterKey.section !== 'tags' && (
          <Form.Field>
            <Select
              options={operators}
              placeholder={'operator'}
              value={this.props.op}
              onChange={(e, {value}) => {
                this.props.setFilterComponent(
                  this.props.kind,
                  this.props.id,
                  'op',
                  value,
                );
              }}
            />
          </Form.Field>
        )}
        {this.props.op === '=' || this.props.op === '!=' ? (
          <Form.Field>
            <Dropdown
              options={this.valueSuggestions}
              placeholder="value"
              search
              selection
              value={this.props.value}
              onChange={(e, {value}) => {
                this.props.setFilterComponent(
                  this.props.kind,
                  this.props.id,
                  'value',
                  value,
                );
              }}
            />
          </Form.Field>
        ) : (
          <Form.Input
            value={this.props.value}
            onChange={(e, {value}) => {
              this.props.setFilterComponent(
                this.props.kind,
                this.props.id,
                'value',
                value,
              );
            }}
          />
        )}
      </Form>
    );
  }
}

class RunFilter extends React.Component {
  componentDidMount() {
    // We want newly added filters to be in the editing state by default. But semantic-ui-react's
    // popup implementation is broken and needs an initial click in order to get the correct
    // position of the popup. Without the initial click it renders the popup at the top of the
    // page.
    // I tried using react's ref mechanism, by creating my own component to pass to the popup
    // trigger, but popup's don't seem to work with custom components that I make, the popup
    // simply never opens, no idea why.
    // So we resort to good old fashined document.getElementById.
    // setTimeout is needed because the click triggers onClose on the previously opened
    // popup, which blindly closes whatever's open.
    if (!this.props.filterKey.section) {
      setTimeout(
        () =>
          document.getElementById('runFilterViewer' + this.props.id).click(),
        1,
      );
    }
    this.fixupDimmer();
  }
  componentWillUnmount() {
    this.props.editFilter(null);
  }

  innerDivRef = ref => {
    console.log('INNER DIV REF', ref);
    this._innerDiv = ref;
    this.fixupDimmer();
  };

  fixupDimmer() {
    // The Edit Panel Modal uses a Semantic React UI Dimmer,
    // which blurs everything that is a direct descendent of body, except
    // elements that have a 'dimmer' class. Popup is created inside of a Portal,
    // but we don't get access to the Portal's dom node. We have to go two
    // levels down and create a div that we can get access to. Something seems
    // to clear the class if we add it on this pass of the event loop, so we
    // use setTimeout.
    console.log('Fixing up dimmer', this._innerDiv);
    setTimeout(() => {
      if (this._innerDiv && this._innerDiv.parentElement) {
        this._portal = this._innerDiv.parentElement.parentElement;
        this._portal.className = 'dimmer';
        this._portal.style = 'position: static';
      }
    }, 0);
  }

  componentWillReceiveProps(nextProps) {
    this.fixupDimmer();
  }

  render() {
    return (
      <Popup
        onMount={this.fixupDimmer}
        trigger={
          <span>
            <Button.Group
              className="runFilterViewer"
              style={{marginRight: 12, marginTop: 8}}
              size="tiny">
              <Button className="filter" id={'runFilterViewer' + this.props.id}>
                {this.props.filterKey.section === 'tags' ? (
                  <span>
                    tags:{this.props.filterKey.value} is{' '}
                    {this.props.value === 'true' ? 'Set' : 'Unset'}
                  </span>
                ) : (
                  <span>
                    <span>
                      {this.props.filterKey.section
                        ? Run.displayFilterKey(this.props.filterKey)
                        : '_'}
                    </span>{' '}
                    <span>{this.props.op ? this.props.op : '_'}</span>{' '}
                    <span>
                      {this.props.value
                        ? Run.displayValue(this.props.value)
                        : '_'}
                    </span>
                  </span>
                )}
              </Button>
              <Button
                negative
                className="delete"
                icon="trash"
                onClick={e => {
                  // prevents triggering Popup click event, that will cause "onOpen" event to be called
                  e.stopPropagation();
                  this.props.deleteFilter(this.props.kind, this.props.id);
                }}
              />
            </Button.Group>
          </span>
        }
        on="click"
        content={
          <div ref={this.innerDivRef}>
            <RunFilterEditor
              runs={this.props.runs}
              kind={this.props.kind}
              id={this.props.id}
              filterKey={this.props.filterKey}
              op={this.props.op}
              value={this.props.value}
              keys={this.props.keys}
              otherFilters={this.props.otherFilters}
              editFilter={this.props.editFilter}
              setFilterComponent={this.props.setFilterComponent}
            />
          </div>
        }
        open={this.props.editing}
        onOpen={() => this.props.editFilter(this.props.id)}
        onClose={() => this.props.editFilter(null)}
        position="bottom center"
        flowing
      />
    );
  }
}

export default class RunFilters extends React.Component {
  state = {editingFilter: null};

  render() {
    let {
      filters,
      allFilters,
      kind,
      runs,
      addFilter,
      deleteFilter,
      setFilterComponent,
      buttonText,
    } = this.props;
    if (!allFilters) {
      allFilters = filters;
    }
    let filterIDs = _.keys(filters).sort();
    let filterKeys = Run.flatKeySuggestions(this.props.keySuggestions);
    return (
      <div>
        <div
          className={this.props.nobox ? '' : 'input-style'}
          style={{marginTop: -4}}>
          {filterIDs.map(filterID => {
            let filter = filters[filterID];
            return (
              <RunFilter
                kind={kind}
                runs={runs}
                key={filter.id}
                id={filter.id}
                filterKey={filter.key}
                op={filter.op}
                value={filter.value}
                keys={filterKeys}
                otherFilters={update(allFilters, {$unset: [filterID]})}
                editing={this.state.editingFilter === filter.id}
                editFilter={id => this.setState({editingFilter: id})}
                deleteFilter={deleteFilter}
                setFilterComponent={setFilterComponent}
              />
            );
          })}
          <Button
            icon="plus"
            disabled={this.props.filteredRuns.length <= 1}
            circular
            content={buttonText}
            style={{marginTop: 8}}
            size="tiny"
            onClick={() => {
              addFilter(kind, {}, '=', '');
            }}
          />
        </div>
      </div>
    );
  }
}
