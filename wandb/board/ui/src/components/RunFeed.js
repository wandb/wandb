import React, {PureComponent} from 'react';
import {
  Button,
  Checkbox,
  Icon,
  Image,
  Table,
  Item,
  Popup,
} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import {NavLink} from 'react-router-dom';
import './RunFeed.css';
import Launcher from '../containers/Launcher';
import FixedLengthString from '../components/FixedLengthString';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {makeShouldUpdate} from '../util/shouldUpdate';

import {
  addFilter,
  enableColumn,
  toggleRunSelection,
  setSort,
} from '../actions/run';
import _ from 'lodash';
// import {JSONparseNaN} from '../util/jsonnan';
import Pagination from './Pagination';
import {
  displayValue,
  getRunValue,
  sortableValue,
  truncateString,
} from '../util/runhelpers.js';
import ContentLoader from 'react-content-loader';

const maxColNameLength = 20;

class ValueDisplay extends PureComponent {
  render() {
    return (
      <Popup
        on="hover"
        hoverable
        position="left center"
        style={{padding: 6}}
        trigger={
          <span className="config">
            {this.props.content ? (
              <span className="value"> {this.props.content} </span>
            ) : (
              <span>
                <span className="value">{displayValue(this.props.value)}</span>{' '}
                {!this.props.justValue && (
                  <span className="key">{this.props.valKey}</span>
                )}
              </span>
            )}
          </span>
        }
        content={
          <span>
            {this.props.enablePopout && (
              <Popup
                on="hover"
                inverted
                size="tiny"
                trigger={
                  <Button
                    style={{padding: 6}}
                    icon="external square"
                    onClick={() => {
                      this.props.enableColumn(
                        this.props.section + ':' + this.props.valKey,
                      );
                    }}
                  />
                }
                content="Pop out"
              />
            )}
            <Popup
              on="hover"
              inverted
              size="tiny"
              trigger={
                <Button
                  style={{padding: 6}}
                  icon="unhide"
                  onClick={() => {
                    let filterKey = {
                      section: this.props.section,
                      value: this.props.valKey,
                    };
                    this.props.addFilter(
                      'filter',
                      filterKey,
                      '=',
                      sortableValue(this.props.value),
                    );
                  }}
                />
              }
              content="Add filter"
            />
          </span>
        }
      />
    );
  }
}

const mapValueDisplayDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({addFilter, enableColumn}, dispatch);
};

ValueDisplay = connect(null, mapValueDisplayDispatchToProps)(ValueDisplay);

class RunFeedHeader extends React.Component {
  constructor(props) {
    super(props);
    // This seems like it would be expensive but it's not (.5ms on a row with ~100 columns)
    this._shouldUpdate = makeShouldUpdate({
      name: 'RunFeedHeader',
      deep: ['columnNames'],
      ignoreFunctions: true,
      debug: false,
    });
  }

  shouldComponentUpdate(nextProps, nextState) {
    return this._shouldUpdate(this.props, nextProps);
  }

  render() {
    let {selectable, sort, columnNames} = this.props;
    let longestColumn =
      Object.assign([], columnNames).sort((a, b) => b.length - a.length)[0] ||
      '';
    return (
      <Table.Header>
        <Table.Row
          style={{
            height: Math.min(longestColumn.length, maxColNameLength) * 8,
          }}>
          {selectable && <Table.HeaderCell />}
          {columnNames.map(columnName => (
            <Table.HeaderCell
              key={columnName}
              className={
                _.startsWith(columnName, 'config:') ||
                _.startsWith(columnName, 'summary:')
                  ? 'rotate'
                  : ''
              }
              style={{textAlign: 'center', verticalAlign: 'bottom'}}
              onClick={() => {
                if (columnName === 'Config' || columnName === 'Summary') {
                  return;
                }
                let ascending = true;
                if (sort.name === columnName) {
                  ascending = !sort.ascending;
                }
                this.props.setSort(columnName, ascending);
              }}>
              <div>
                {_.startsWith(columnName, 'config:') ||
                _.startsWith(columnName, 'summary:') ? (
                  ((columnName = columnName.split(':')[1]),
                  columnName.length > maxColNameLength ? (
                    <span key={columnName}>
                      {truncateString(columnName, maxColNameLength)}
                    </span>
                  ) : (
                    <span>{columnName}</span>
                  ))
                ) : (
                  <span>{columnName}</span>
                )}

                {sort.name === columnName &&
                  (sort.ascending ? (
                    <Icon name="caret up" />
                  ) : (
                    <Icon name="caret down" />
                  ))}
              </div>
            </Table.HeaderCell>
          ))}
        </Table.Row>
      </Table.Header>
    );
  }
}

class RunFeedRow extends React.Component {
  constructor(props) {
    super(props);
    // This seems like it would be expensive but it's not (.5ms on a row with ~100 columns)
    this._shouldUpdate = makeShouldUpdate({
      name: 'RunRow',
      deep: ['run', 'selectedRuns', 'columnNames'],
      ignoreFunctions: true,
      debug: false,
    });
  }

  shouldComponentUpdate(nextProps, nextState) {
    return this._shouldUpdate(this.props, nextProps, this.props.run.name);
  }

  stateToIcon(state) {
    let icon = 'check',
      color = 'green';
    if (state === 'failed' || state === 'crashed') {
      icon = 'remove';
      color = 'red';
    } else if (state === 'killed') {
      icon = 'remove user';
      color = 'orange';
    } else if (state === 'running') {
      icon = 'spinner';
      color = 'blue';
    }
    return <Icon name={icon} color={color} loading={state === 'running'} />;
  }

  descriptionCell(edge) {
    let {loading, project, admin} = this.props;
    return (
      <Table.Cell className="overview" key="Description">
        {loading && (
          <ContentLoader
            style={{height: 43}}
            height={63}
            width={350}
            speed={2}
            primaryColor={'#f3f3f3'}
            secondaryColor={'#e3e3e3'}>
            <circle cx="32" cy="32" r="30" />
            <rect x="75" y="13" rx="4" ry="4" width="270" height="13" />
            <rect x="75" y="40" rx="4" ry="4" width="50" height="8" />
          </ContentLoader>
        )}
        {!loading && (
          <Item.Group>
            <Item>
              <Item.Image size="tiny" style={{width: 40}}>
                <Image
                  src={edge.user && edge.user.photoUrl}
                  size="mini"
                  style={{borderRadius: '500rem'}}
                />
              </Item.Image>
              <Item.Content>
                <Item.Header>
                  <NavLink
                    to={`/${project.entityName}/${project.name}/runs/${
                      edge.name
                    }`}>
                    {edge.description || edge.name
                      ? (edge.description || edge.name).split('\n')[0]
                      : ''}{' '}
                    {this.stateToIcon(edge.state)}
                  </NavLink>
                </Item.Header>
                <Item.Extra style={{marginTop: 0}}>
                  <strong>{edge.user && edge.user.username}</strong>
                  {/* edge.host && `on ${edge.host} ` */}
                  {/*edge.fileCount + ' files saved' NOTE: to add this back, add fileCount back to RUNS_QUERY*/}
                </Item.Extra>
                {admin && <Launcher runId={edge.id} runName={edge.name} />}
              </Item.Content>
            </Item>
          </Item.Group>
        )}
      </Table.Cell>
    );
  }

  render() {
    let {
      run,
      selectable,
      selectedRuns,
      loading,
      columnNames,
      project,
    } = this.props;
    const summary = run.summary;
    const config = run.config;
    return (
      <Table.Row key={run.id}>
        {selectable && (
          <Table.Cell collapsing>
            <Checkbox
              checked={!!selectedRuns[run.name]}
              onChange={() => this.props.toggleRunSelection(run.name, run.id)}
            />
          </Table.Cell>
        )}
        {columnNames.map(columnName => {
          if (columnName === 'Description') {
            return this.descriptionCell(run);
          } else if (columnName === 'Sweep') {
            return (
              <Table.Cell key="stop" collapsing>
                {run.sweep && (
                  <ValueDisplay
                    section="sweep"
                    valKey="name"
                    value={run.sweep.name}
                    content={
                      <NavLink
                        to={`/${project.entityName}/${project.name}/sweeps/${
                          run.sweep.name
                        }`}>
                        {run.sweep.name}
                      </NavLink>
                    }
                  />
                )}
              </Table.Cell>
            );
          } else if (columnName === 'Ran') {
            return (
              <Table.Cell key={columnName} collapsing>
                <TimeAgo date={run.createdAt + 'Z'} />
              </Table.Cell>
            );
          } else if (columnName === 'Runtime') {
            return (
              <Table.Cell key={columnName} collapsing>
                {run.heartbeatAt && (
                  <TimeAgo
                    date={run.createdAt + 'Z'}
                    now={() => {
                      return Date.parse(run.heartbeatAt + 'Z');
                    }}
                    formatter={(v, u, s, d, f) => f().replace(s, '')}
                    live={false}
                  />
                )}
              </Table.Cell>
            );
          } else if (columnName === 'Stop') {
            return (
              <Table.Cell key="stop" collapsing>
                {run.shouldStop}
              </Table.Cell>
            );
          } else {
            let key = columnName.split(':')[1];
            return (
              <Table.Cell
                key={columnName}
                style={{
                  maxWidth: 200,
                  direction: 'rtl',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
                collapsing>
                <ValueDisplay
                  section="config"
                  valKey={key}
                  value={getRunValue(run, columnName)}
                  justValue
                />
              </Table.Cell>
            );
          }
        })}
      </Table.Row>
    );
  }
}

class RunFeed extends PureComponent {
  static defaultProps = {
    currentPage: 1,
  };
  state = {sort: 'timeline', dir: 'descending'};

  sortedClass(type) {
    return this.state.sort === type ? `sorted ${this.state.dir}` : '';
  }

  onSort(name) {
    let dir = this.state.dir;
    if (this.state.sort === name) {
      dir = this.state.dir === 'descending' ? 'ascending' : 'descending';
      this.setState({dir: dir});
    } else {
      this.setState({sort: name});
    }
    this.props.onSort(name, dir);
  }

  tablePlaceholders(limit, length) {
    let pageLength = !length || length > limit ? limit : length;
    return Array.from({length: pageLength}).map((x, i) => {
      return {id: i};
    });
  }

  render() {
    let /*stats =
        this.props.project &&
        Object.keys(JSONparseNaN(this.props.project.summaryMetrics)).sort(),*/
      runsLength = this.props.runs && this.props.runs.length,
      startIndex = (this.props.currentPage - 1) * this.props.limit,
      endIndex = Math.min(startIndex + this.props.limit, runsLength),
      runs =
        this.props.runs && this.props.runs.length > 0 && !this.props.loading
          ? this.props.runs.slice(startIndex, endIndex)
          : this.tablePlaceholders(
              this.props.limit,
              this.props.project.bucketCount,
            ),
      columnNames = this.props.loading
        ? ['Description']
        : this.props.columnNames.filter(
            columnName => this.props.columns[columnName],
          );
    return (
      <div>
        <div className="runsTable">
          <Table
            definition={this.props.selectable}
            celled
            sortable
            compact
            unstackable
            size="small">
            <RunFeedHeader
              selectable={this.props.selectable}
              sort={this.props.sort}
              columnNames={columnNames}
            />
            <Table.Body>
              {runs &&
                runs.map((run, i) => (
                  <RunFeedRow
                    key={i}
                    run={run}
                    selectable={this.props.selectable}
                    selectedRuns={this.props.selectedRuns}
                    loading={this.props.loading}
                    columnNames={columnNames}
                    project={this.props.project}
                  />
                ))}
            </Table.Body>
          </Table>
        </div>
        <Pagination
          id={this.props.project.id}
          total={runsLength}
          limit={this.props.limit}
          scroll={false}
        />
      </div>
    );
  }
}

function autoConfigCols(runs) {
  runs = runs.filter(run => run.config);
  if (runs.length <= 1) {
    return [];
  }
  let allKeys = _.uniq(_.flatMap(runs, run => _.keys(run.config)));
  let result = {};
  for (let key of allKeys) {
    let vals = runs.map(run => run.config[key]);
    let types = _.uniq(vals.map(val => typeof val));
    if (types.length !== 1) {
      // Show columns that have different types
      result[key] = true;
    } else {
      let type = types[0];
      let uniqVals = _.uniq(vals);
      if (type === 'string') {
        // Show columns that have differing values unless all values differ
        if (uniqVals.length > 1 && uniqVals.length < vals.length) {
          result[key] = true;
        } else {
          result[key] = false;
        }
      } else {
        if (vals.every(val => _.isArray(val) && val.length === 0)) {
          // Special case for empty arrays, we don't get non-empty arrays
          // as config values because of the flattening that happens at a higher
          // layer.
          result[key] = false;
        } else {
          // Show columns that have differing values even if all values differ
          if (uniqVals.length > 1) {
            result[key] = true;
          } else {
            result[key] = false;
          }
        }
      }
    }
  }
  return _.mapKeys(result, (value, key) => 'config:' + key);
}

function mapStateToProps() {
  let prevColumns = null;
  let prevRuns = null;
  let cols = {};
  let autoCols = {};

  return function(state, ownProps) {
    const id = ownProps.project.id;
    if (state.runs.columns !== prevColumns || ownProps.runs !== prevRuns) {
      prevColumns = state.runs.columns;
      prevRuns = ownProps.runs;
      if (state.runs.columns['_ConfigAuto']) {
        // Only update the autoCols when the total amount of runs goes down
        // (i.e. the user is performing a filtering operation). This could
        // cause us to be incorrect if individual runs config columns are
        // being updated by subscriptions.
        if (
          _.keys(autoCols).length < 10 ||
          ownProps.runs.length < prevRuns.length
        ) {
          autoCols = autoConfigCols(ownProps.runs);
        }
        cols = {...state.runs.columns, ...autoCols};
      } else {
        cols = state.runs.columns;
      }
    }
    return {
      columns: cols,
      sort: state.runs.sort,
      currentPage: state.runs.pages[id] && state.runs.pages[id].current,
    };
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({toggleRunSelection, setSort}, dispatch);
};

export default connect(mapStateToProps(), mapDispatchToProps)(RunFeed);
