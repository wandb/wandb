import update from 'immutability-helper';
import * as _ from 'lodash';
import * as React from 'react';
import {graphql, OptionProps, QueryProps} from 'react-apollo';
import {Button, Dropdown, Form, Popup, Select} from 'semantic-ui-react';
import {setFilters} from '../actions/run';
import RunKeySelector from '../components/RunKeySelector';
import {
  FILTER_KEY_SUGGESTIONS,
  FILTER_VALUE_SUGGESTIONS,
} from '../graphql/filters';
import * as Filter from '../util/filters';
import * as RunHelpers from '../util/runhelpers';
import * as Run from '../util/runs';

import './RunFilters.css';

interface FilterValueSuggestionsProps {
  entityName: string;
  projectName: string;
  otherFilters: Filter.Filter;
  keysLoading: boolean;
  keyPath: string | undefined;
  filter: Filter.IndividualFilter;
  setFilterValue(value: Run.Value): void;
  setFilterMultiValue(value: Run.Value[]): void;
  close(): void;
}

// Result of the gql query
interface FilterValueSuggestionsResponse {
  project?: {
    valueCounts: string;
  };
}

type ValueCounts = Array<{value: Run.Value; count: number}>;

interface FilterValueSuggestionsResponseParsed {
  loading?: boolean;
  valueOptions?: ValueOptions;
}

const withFilterValueSuggestions = graphql<
  FilterValueSuggestionsResponse,
  FilterValueSuggestionsProps,
  FilterValueSelectorProps
>(FILTER_VALUE_SUGGESTIONS, {
  skip: ({keyPath}) => !keyPath,
  options: ({entityName, projectName, keyPath, otherFilters}) => {
    return {
      variables: {
        entityName,
        name: projectName,
        filters: JSON.stringify(Filter.toMongo(otherFilters)),
        keyPath,
      },
    };
  },
  props: ({data, ownProps}) => {
    if (data == null) {
      // data is never null when doing a query (rather than mutation), but the apollo-react
      // types don't account for this.
      throw new Error('data == null for graphql query');
    }
    return {
      loading: data.loading,
      valueOptions:
        // Not sure why we need to check data.project.valueCounts here, but we get two calls, one with
        // just id and name, and then a second with valueCounts
        data.project && data.project.valueCounts
          ? parseFilterValueSuggestions(
              ownProps.filter.key,
              data.project.valueCounts
            )
          : [],
    };
  },
});

function displayValue(filterKey: Run.Key, value: Run.Value) {
  if (filterKey.section === 'tags') {
    return value === true ? 'Set' : 'Unset';
  } else {
    return Run.displayValue(value);
  }
}

function parseFilterValueSuggestions(
  filterKey: Run.Key,
  valueCountsString: string
): ValueOptions {
  const json = JSON.parse(valueCountsString);
  return json.values
    .map((valCount: any) => {
      if (
        !_.isArray(valCount) ||
        valCount.length !== 2 ||
        !_.isNumber(valCount[1])
      ) {
        console.warn('invalid valueCount', valCount);
        return null;
      }
      const value = Run.parseValue(valCount[0]);
      const count: number = valCount[1];
      const displayVal = displayValue(filterKey, value);
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
    })
    .filter((o: any) => o);
}

type ValueOptions = Array<{
  text: string;
  value: string | number;
  key: string | number;
  content: React.ReactNode;
}>;

type FilterValueSelectorProps = FilterValueSuggestionsProps &
  FilterValueSuggestionsResponseParsed;
class FilterValueSelector extends React.Component<
  FilterValueSelectorProps,
  {}
> {
  render() {
    return (
      <Dropdown
        loading={this.props.keysLoading || this.props.loading}
        additionLabel=""
        allowAdditions
        options={this.props.valueOptions}
        placeholder="value"
        search
        selection
        multiple={Filter.isMultiValue(this.props.filter)}
        value={Filter.domValue(this.props.filter)}
        onChange={(e, {value}) => {
          if (value) {
            if (Filter.isMultiValue(this.props.filter)) {
              if (
                !(typeof value === 'string') &&
                !(typeof value === 'number')
              ) {
                this.props.setFilterMultiValue(value.map(Run.parseValue));
              }
            } else {
              this.props.setFilterValue(Run.parseValue(value));
            }
          }
        }}
        onClose={() => this.props.close()}
      />
    );
  }
}
const FilterValueSelectorWrapped = withFilterValueSuggestions(
  FilterValueSelector
);

// This is what's passed in to the FilterKeySuggestions HOC
interface FilterKeySuggestionsProps {
  entityName: string;
  projectName: string;
  filter: Filter.IndividualFilter;
  otherFilters: Filter.Filter;
  id: number;
  setFilterKey(key: Run.Key): void;
  setFilterOp(op: Filter.IndividualOp): void;
  setFilterValue(value: Run.Value): void;
  setFilterMultiValue(value: Run.Value[]): void;
  close(): void;
}

// This is the result of the gql query
interface FilterKeySuggestionsResponse {
  project?: {
    pathCounts: string;
  };
}

interface KeyToPath {
  [key: string]: string;
}

interface FilterKeySuggestionsResponseParsed {
  loading: boolean;
  keys: string[];
  keyToPath: KeyToPath;
}

const withFilterKeySuggestions = graphql<
  FilterKeySuggestionsResponse,
  FilterKeySuggestionsProps,
  RunFilterEditorProps
>(FILTER_KEY_SUGGESTIONS, {
  options: ({entityName, projectName, otherFilters}) => {
    return {
      variables: {
        entityName,
        name: projectName,
        filters: JSON.stringify(Filter.toMongo(otherFilters)),
      },
    };
  },
  props: ({data}) => {
    if (data == null) {
      // data is never null when doing a query (rather than mutation), but the apollo-react
      // types don't account for this.
      throw new Error('data == null for graphql query');
    }
    const keyToPath = data.project
      ? parseFilterKeySuggestions(data.project.pathCounts)
      : {};
    return {
      loading: data.loading,
      keys: _.keys(keyToPath).sort(),
      keyToPath,
    };
  },
});

function parseFilterKeySuggestions(pathCountsString: string): KeyToPath {
  const json = JSON.parse(pathCountsString);
  if (!_.isObject(json)) {
    return {};
  }
  return _.fromPairs(
    _.keys(json)
      .map(path => [Run.serverPathToKeyString(path), path])
      .filter(([key, path]) => key)
  );
}

let globalFilterId = 0;
type RunFilterEditorProps = FilterKeySuggestionsProps &
  FilterKeySuggestionsResponseParsed;
class RunFilterEditor extends React.Component<RunFilterEditorProps, {}> {
  valueSuggestions: any;

  componentDidMount() {
    const el = document.getElementById(this.elementId());
    if (this.props.filter.key.name === '' && el) {
      const inputs = el.getElementsByTagName('input');
      if (inputs.length > 0) {
        inputs[0].focus();
      }
    }
  }

  elementId() {
    return 'filtereditor-' + this.props.id;
  }

  render() {
    const operators = ['=', '!=', '>=', '<=', 'IN'].map(op => ({
      text: op,
      value: op,
    }));
    return (
      <div style={{position: 'relative'}}>
        <Form id={this.elementId()}>
          <Form.Field>
            <RunKeySelector
              loading={this.props.loading}
              keys={this.props.keys}
              storedKey={Run.displayKey(this.props.filter.key)}
              onValidSelection={keyString => {
                const filterKey = Run.keyFromString(keyString);
                if (filterKey != null) {
                  this.props.setFilterKey(filterKey);
                }
              }}
              disabled={this.props.loading}
            />
          </Form.Field>
          {this.props.filter.key.section !== 'tags' && (
            <Form.Field>
              <Select
                loading={this.props.loading}
                options={operators}
                placeholder={'operator'}
                value={this.props.filter.op}
                onChange={(e, {value}) => {
                  this.props.setFilterOp(value as Filter.IndividualOp);
                }}
              />
            </Form.Field>
          )}
          <Form.Field>
            <FilterValueSelectorWrapped
              entityName={this.props.entityName}
              projectName={this.props.projectName}
              otherFilters={this.props.otherFilters}
              keysLoading={this.props.loading}
              keyPath={
                this.props.keyToPath[Run.displayKey(this.props.filter.key)]
              }
              filter={this.props.filter}
              setFilterValue={this.props.setFilterValue}
              setFilterMultiValue={this.props.setFilterMultiValue}
              close={this.props.close}
            />
          </Form.Field>
        </Form>
      </div>
    );
  }
}

const RunFilterEditorWrapped = withFilterKeySuggestions(RunFilterEditor);

interface RunFilterProps {
  entityName: string;
  projectName: string;
  filter: Filter.IndividualFilter;
  otherFilters: Filter.Filter;
  editing: boolean;
  id: string;
  editFilter(id: string): void;
  deleteFilter(): void;
  setFilter(filter: Filter.IndividualFilter): void;
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
    return 'runFilterViewer' + this.globalId;
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
                    <span>
                      {value != null
                        ? Filter.displayIndividualValue(this.props.filter)
                        : '-'}
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
                  this.props.deleteFilter();
                }}
              />
            </Button.Group>
          </span>
        }
        on="click"
        content={
          <div ref={this.innerDivRef}>
            <RunFilterEditorWrapped
              entityName={this.props.entityName}
              projectName={this.props.projectName}
              filter={this.props.filter}
              otherFilters={this.props.otherFilters}
              id={this.globalId}
              setFilterKey={(filterKey: Run.Key) =>
                this.props.setFilter({
                  ...this.props.filter,
                  key: filterKey,
                })
              }
              setFilterOp={(filterOp: Filter.IndividualOp) => {
                const isMulti = Filter.isMultiValue(this.props.filter);
                let filter: Filter.IndividualFilter = this.props.filter;
                if (Filter.isMultiValue(this.props.filter)) {
                  if (!Filter.isMultiOp(filterOp)) {
                    let val = null;
                    if (this.props.filter.value.length > 0) {
                      val = this.props.filter.value[0];
                    }
                    filter = {
                      key: this.props.filter.key,
                      op: filterOp,
                      value: val,
                    };
                  }
                } else {
                  if (Filter.isMultiOp(filterOp)) {
                    filter = {
                      key: this.props.filter.key,
                      op: filterOp,
                      value:
                        this.props.filter.value != null &&
                        this.props.filter.value !== '*'
                          ? [this.props.filter.value]
                          : [],
                    };
                  } else {
                    filter = {
                      key: this.props.filter.key,
                      op: filterOp,
                      value: this.props.filter.value,
                    };
                  }
                }
                this.props.setFilter(filter);
              }}
              setFilterValue={(filterValue: Run.Value) => {
                this.props.setFilter({
                  ...this.props.filter,
                  value: filterValue,
                } as Filter.ValueFilter);
              }}
              setFilterMultiValue={(filterValue: Run.Value[]) => {
                this.props.setFilter({
                  ...this.props.filter,
                  value: filterValue,
                } as Filter.MultiValueFilter);
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
  entityName: string;
  projectName: string;
  filters: Filter.Filter;
  mergeFilters: Filter.Filter | null;
  index: number;
  editingId: string;
  canAdd: boolean;
  editFilter(id: string): void;
  pushFilter(filter: Filter.Filter): void;
  deleteFilter(index: number): void;
  setFilter(index: number, filter: Filter.IndividualFilter): void;
}
export class RunFiltersSection extends React.Component<
  RunFiltersSectionProps,
  {}
> {
  render() {
    const {filters, mergeFilters, editingId} = this.props;
    return filters.op === 'AND' ? (
      <div className="runFiltersSection">
        {this.props.index !== 0 && 'OR '}
        {filters.filters.map((filter, i) => {
          const filterId = this.props.index.toString() + i;
          let otherFilters = Filter.Update.groupRemove(filters, [], i);
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
              entityName={this.props.entityName}
              projectName={this.props.projectName}
              key={filterId}
              filter={filter}
              otherFilters={otherFilters}
              id={filterId}
              editing={editingId === filterId}
              editFilter={(id: string) => this.props.editFilter(id)}
              deleteFilter={() => this.props.deleteFilter(i)}
              setFilter={(f: Filter.IndividualFilter) =>
                this.props.setFilter(i, f)
              }
            />
          );
        })}
        <Button
          icon="plus"
          disabled={!this.props.canAdd}
          className="andButton"
          circular
          content="AND"
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
  entityName: string;
  projectName: string;
  filters: Filter.Filter;
  mergeFilters: Filter.Filter | null;
  kind: string;
  filteredRunsCount: number;
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
    const {mergeFilters, kind, nobox} = this.props;
    let modFilters = Filter.simplify(this.props.filters);
    let empty = false;
    if (modFilters == null) {
      empty = true;
      modFilters = {op: 'OR', filters: [{op: 'AND', filters: []}]};
    }
    const filters: Filter.Filter = modFilters;
    return filters.op === 'OR' ? (
      <div className={empty ? 'runFiltersEmpty' : 'runFilters'}>
        {filters.filters.map((filter, i) => (
          <RunFiltersSection
            entityName={this.props.entityName}
            projectName={this.props.projectName}
            key={i}
            filters={filter}
            mergeFilters={mergeFilters}
            index={i}
            editingId={this.state.editingId}
            canAdd={this.props.filteredRunsCount > 1}
            editFilter={(id: string) => this.setState({editingId: id})}
            pushFilter={(newFilter: Filter.Filter) => {
              this.props.setFilters(
                kind,
                Filter.Update.groupPush(filters, [i], newFilter)
              );
            }}
            deleteFilter={(index: number) =>
              this.props.setFilters(
                kind,
                Filter.Update.groupRemove(filters, [i], index)
              )
            }
            setFilter={(index: number, f: Filter.Filter) =>
              this.props.setFilters(
                kind,
                Filter.Update.setFilter(filters, [i, index], f)
              )
            }
          />
        ))}
        <Button
          className="orButton"
          circular
          icon="plus"
          content="OR"
          style={{marginTop: 8}}
          size="tiny"
          onClick={() =>
            this.props.setFilters(
              kind,
              Filter.Update.groupPush(filters, [], {
                op: 'AND',
                filters: [
                  {key: {section: 'run', name: ''}, op: '=', value: null},
                ],
              })
            )
          }
        />
      </div>
    ) : (
      <p>Can't render filters</p>
    );
  }
}
