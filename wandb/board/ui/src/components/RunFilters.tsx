import update from 'immutability-helper';
import * as _ from 'lodash';
import * as React from 'react';
import {Button, Dropdown, Form, Popup, Select} from 'semantic-ui-react';
import {setFilters} from '../actions/run';
import RunKeySelector from '../components/RunKeySelector';
import * as Filter from '../util/filters';
import * as RunHelpers from '../util/runhelpers';
import * as RunHelpers2 from '../util/runhelpers2';
import * as Run from '../util/runs';

import './RunFilters.css';

let globalFilterId = 0;
interface RunFilterEditorProps {
  runs: Run.Run[];
  keys: string[];
  filterKey: Run.Key;
  op: Filter.IndividiualOp;
  value: Run.Value;
  id: number;
  otherFilters: Filter.Filter;
  setFilterKey(key: Run.Key): void;
  setFilterOp(op: Filter.IndividiualOp): void;
  setFilterValue(value: Run.Value): void;
  close(): void;
}
class RunFilterEditor extends React.Component<RunFilterEditorProps, {}> {
  keyValueCounts: RunHelpers2.KeyValueCount = {};
  valueSuggestions: any;

  componentWillMount() {
    console.log('editor props', this.props);
    const filtered = Filter.filterRuns(
      this.props.otherFilters,
      this.props.runs,
    );
    this.keyValueCounts = RunHelpers2.keyValueCounts(filtered, this.props.keys);
    console.log('GOT KVC', this.keyValueCounts);
    this.setupValueSuggestions(this.props);
  }

  componentDidMount() {
    const el = document.getElementById(this.elementId());
    if (this.props.filterKey.name === '' && el) {
      const inputs = el.getElementsByTagName('input');
      if (inputs.length > 0) {
        inputs[0].focus();
      }
    }
  }

  elementId() {
    return 'filtereditor-' + this.props.id;
  }

  displayValue(value: Run.Value) {
    if (this.props.filterKey.section === 'tags') {
      return value === true ? 'Set' : 'Unset';
    } else {
      return Run.displayValue(value);
    }
  }

  setupValueSuggestions(props: RunFilterEditorProps) {
    const keyString = Run.displayKey(this.props.filterKey);
    let valueCounts = keyString ? this.keyValueCounts[keyString] : null;
    if (valueCounts) {
      if (this.props.filterKey.section === 'tags') {
        // We want true before false
        valueCounts = [...valueCounts].reverse();
      } else if (props.op === '=' || props.op === '!=') {
        valueCounts = [{value: '*', count: 0}, ...valueCounts];
      }
      this.valueSuggestions = valueCounts.map(({value, count}) => {
        const displayVal = this.displayValue(value);
        return {
          text: displayVal,
          key: Run.domValue(value),
          value: Run.domValue(value),
          content: (
            <span
              style={{
                display: 'inline-block',
                width: '100%',
              }}
              key={displayVal}>
              <span
                style={{
                  display: 'inline-block',
                  whitespace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                {displayVal}
              </span>
              {value !== '*' && (
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
        };
      });
      console.log(
        'VALUE auto check',
        this.props.value,
        this.valueSuggestions.length,
      );
      if (this.props.value == null && this.valueSuggestions.length > 0) {
        console.log('SETTING VALUE AUTO', this.valueSuggestions[0].value);
        this.props.setFilterValue(this.valueSuggestions[0].value);
      }
    } else {
      this.valueSuggestions = [];
    }
  }

  componentWillReceiveProps(nextProps: RunFilterEditorProps) {
    this.setupValueSuggestions(nextProps);
  }

  render() {
    const operators = ['=', '!=', '>=', '<='].map(op => ({
      text: op,
      value: op,
    }));
    console.log('VALUE', this.props.value);
    return (
      <Form id={this.elementId()}>
        <Form.Field>
          <RunKeySelector
            keys={
              _.map(
                this.keyValueCounts,
                (valueCounts, key) =>
                  _.keys(valueCounts).length > 1 ? key : null,
              ).filter(o => o) as string[]
            }
            storedKey={Run.displayKey(this.props.filterKey)}
            onValidSelection={keyString => {
              const filterKey = Run.keyFromString(keyString);
              if (filterKey != null) {
                this.props.setFilterKey(filterKey);
              }
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
                this.props.setFilterOp(value as Filter.IndividiualOp);
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
              value={Run.domValue(this.props.value)}
              onChange={(e, {value}) => {
                let parsedValue = null;
                if (typeof value === 'number') {
                  parsedValue = value;
                }
                if (value === 'true') {
                  parsedValue = true;
                } else if (value === 'false') {
                  parsedValue = false;
                } else if (value === 'null') {
                  parsedValue = null;
                } else if (typeof value === 'string') {
                  parsedValue = value;
                }
                this.props.setFilterValue(parsedValue);
                this.props.close();
              }}
            />
          </Form.Field>
        ) : (
          <Form.Input
            value={this.props.value}
            onChange={(e, {value}) => {
              let parsedValue: Run.Value = parseFloat(value);
              if (
                (typeof value === 'string' && value.search('.') !== -1) ||
                isNaN(parsedValue)
              ) {
                if (value === 'true') {
                  parsedValue = true;
                } else if (value === 'false') {
                  parsedValue = false;
                } else if (value === 'null') {
                  parsedValue = null;
                } else if (typeof value === 'string') {
                  parsedValue = value;
                }
              }
              this.props.setFilterValue(parsedValue);
            }}
          />
        )}
      </Form>
    );
  }
}

interface RunFilterProps {
  runs: Run.Run[];
  keys: string[];
  filter: Filter.IndividualFilter;
  otherFilters: Filter.Filter;
  editing: boolean;
  id: string;
  editFilter(id: string): void;
  deleteFilter(): void;
  setFilter(filter: Filter.Filter): void;
}
class RunFilter extends React.Component<RunFilterProps, {}> {
  innerDiv: any;
  portal: any;
  globalId: number = 0;

  componentDidMount() {
    this.globalId = globalFilterId;
    globalFilterId++;
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
    if (Filter.isEmpty(this.props.filter)) {
      setTimeout(() => {
        const el = document.getElementById(this.elementId());
        if (el) {
          el.click();
        }
      }, 1);
    }
    this.fixupDimmer();
  }
  componentWillUnmount() {
    this.props.editFilter('');
  }

  elementId() {
    return 'runFilterViewer' + globalFilterId;
  }

  innerDivRef = (ref: any) => {
    this.innerDiv = ref;
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
    setTimeout(() => {
      if (this.innerDiv && this.innerDiv.parentElement) {
        this.portal = this.innerDiv.parentElement.parentElement;
        this.portal.className = 'dimmer';
        this.portal.style = 'position: static';
      }
    }, 0);
  }

  componentWillReceiveProps() {
    this.fixupDimmer();
  }

  render() {
    const {key, op, value} = this.props.filter;
    return (
      <Popup
        onMount={this.fixupDimmer}
        trigger={
          <span>
            <Button.Group
              className="runFilterViewer"
              style={{marginRight: 12, marginTop: 8}}
              size="tiny">
              <Button className="filter" id={this.elementId()}>
                {key.section === 'tags' ? (
                  <span>
                    tags:{key.name} is {value === true ? 'Set' : 'Unset'}
                  </span>
                ) : (
                  <span>
                    <span>{Run.displayKey(key)}</span>{' '}
                    <span>{op ? op : '_'}</span>{' '}
                    <span>{value != null ? Run.displayValue(value) : '-'}</span>
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
                  this.props.deleteFilter();
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
              filterKey={key}
              op={op}
              value={value}
              keys={this.props.keys}
              otherFilters={this.props.otherFilters}
              id={this.globalId}
              setFilterKey={(filterKey: Run.Key) =>
                this.props.setFilter({
                  ...this.props.filter,
                  key: filterKey,
                })
              }
              setFilterOp={(filterOp: Filter.IndividiualOp) =>
                this.props.setFilter({...this.props.filter, op: filterOp})
              }
              setFilterValue={(filterValue: Run.Value) => {
                console.log(
                  'setting filter value',
                  filterValue,
                  this.props.filter,
                  {...this.props.filter, value: filterValue},
                );
                this.props.setFilter({
                  ...this.props.filter,
                  value: filterValue,
                });
              }}
              close={() => this.props.editFilter('')}
            />
          </div>
        }
        open={this.props.editing}
        onOpen={() => this.props.editFilter(this.props.id)}
        onClose={() => this.props.editFilter('')}
        position="bottom center"
        flowing
      />
    );
  }
}

interface RunFiltersSectionProps {
  filters: Filter.Filter;
  mergeFilters: Filter.Filter | null;
  runs: Run.Run[];
  keySuggestions: string[];
  index: number;
  editingId: string;
  canAdd: boolean;
  editFilter(id: string): void;
  pushFilter(filter: Filter.Filter): void;
  deleteFilter(index: number): void;
  setFilter(index: number, filter: Filter.Filter): void;
}
export class RunFiltersSection extends React.Component<
  RunFiltersSectionProps,
  {}
> {
  render() {
    const {filters, mergeFilters, runs, keySuggestions, editingId} = this.props;
    return filters.op === 'AND' ? (
      <div>
        {filters.filters.map((filter, i) => {
          const filterId = this.props.index.toString() + i;
          let otherFilters: Filter.Filter = update(
            filters,
            Filter.Update.groupRemove([], i),
          );
          console.log(
            'other',
            filters,
            Filter.Update.groupRemove([], i),
            otherFilters,
          );
          if (mergeFilters) {
            otherFilters = {
              op: 'AND',
              filters: [mergeFilters, otherFilters],
            };
          }
          if (!Filter.isIndividual(filter)) {
            return <p>Can't render filter</p>;
          }
          return (
            <RunFilter
              key={filterId}
              runs={runs}
              keys={keySuggestions}
              filter={filter}
              otherFilters={otherFilters}
              id={filterId}
              editing={editingId === filterId}
              editFilter={(id: string) => this.props.editFilter(id)}
              deleteFilter={() => this.props.deleteFilter(i)}
              setFilter={(f: Filter.Filter) => this.props.setFilter(i, f)}
            />
          );
        })}
        <Button
          icon="plus"
          disabled={!this.props.canAdd}
          circular
          content="Add Filter"
          style={{marginTop: 8}}
          size="tiny"
          onClick={() =>
            this.props.pushFilter({
              key: {section: 'run', name: ''},
              op: '=',
              value: null,
            })
          }
        />
      </div>
    ) : (
      <p>RunFiltersSection</p>
    );
  }
}

interface RunFiltersProps {
  filters: Filter.Filter;
  mergeFilters: Filter.Filter | null;
  kind: string;
  runs: Run.Run[];
  filteredRuns: Run.Run[];
  keySuggestions: string[];
  nobox: boolean;
  setFilters(kind: string, filters: Filter.Filter): void;
}
interface RunFiltersState {
  editingId: string;
}
export default class RunFilters extends React.Component<
  RunFiltersProps,
  RunFiltersState
> {
  state = {editingId: ''};

  render() {
    const {
      filters,
      mergeFilters,
      kind,
      runs,
      keySuggestions,
      nobox,
    } = this.props;
    const filterIDs = _.keys(filters).sort();
    return filters.op === 'OR' ? (
      <div>
        {filters.filters.map((filter, i) => (
          <RunFiltersSection
            key={i}
            runs={runs}
            keySuggestions={keySuggestions}
            filters={filter}
            mergeFilters={mergeFilters}
            index={i}
            editingId={this.state.editingId}
            canAdd={this.props.filteredRuns.length > 1}
            editFilter={(id: string) => this.setState({editingId: id})}
            pushFilter={(newFilter: Filter.Filter) => {
              console.log(
                'Updated',
                Filter.Update.groupPush([i], newFilter),
                update(filters, Filter.Update.groupPush([i], newFilter)),
              );
              this.props.setFilters(
                kind,
                update(filters, Filter.Update.groupPush([i], newFilter)),
              );
            }}
            deleteFilter={(index: number) =>
              this.props.setFilters(
                kind,
                update(filters, Filter.Update.groupRemove([i], index)),
              )
            }
            setFilter={(index: number, f: Filter.Filter) =>
              this.props.setFilters(
                kind,
                update(filters, Filter.Update.setFilter([i, index], f)),
              )
            }
          />
        ))}
        {/* <Button
          icon="plus"
          circular
          content="Add Filter"
          style={{marginTop: 8}}
          size="tiny"
        /> */}
      </div>
    ) : (
      <p>Can't render filters</p>
    );
  }
}
