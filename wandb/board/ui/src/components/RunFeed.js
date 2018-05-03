import React, {PureComponent} from 'react';
import {
  Button,
  Checkbox,
  Icon,
  Image,
  Label,
  Loader,
  Table,
  Item,
  Popup,
} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import {NavLink} from 'react-router-dom';
import './RunFeed.css';
import Launcher from '../containers/Launcher';
import FixedLengthString from '../components/FixedLengthString';
import Tags from '../components/Tags';
import RunFeedDescription from './RunFeedDescription';
import RunFeedCell from './RunFeedCell';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {makeShouldUpdate} from '../util/shouldUpdate';
import {setFilters, enableColumn, setSort} from '../actions/run';
import _ from 'lodash';
// import {JSONparseNaN} from '../util/jsonnan';
import Pagination from './Pagination';
import {
  displayValue,
  getRunValue,
  sortableValue,
  stateToIcon,
  truncateString,
  getColumns,
} from '../util/runhelpers.js';
import withRunsDataLoader from '../containers/RunsDataLoader';
import ContentLoader from 'react-content-loader';
import * as Selection from '../util/selections';
import * as Filter from '../util/filters';

const maxColNameLength = 20;

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
    let {sort, columnNames} = this.props;
    let longestColumn =
      Object.assign([], columnNames).sort((a, b) => b.length - a.length)[0] ||
      '';
    return (
      <Table.Header>
        <Table.Row
          style={{
            height: Math.min(longestColumn.length, maxColNameLength) * 8,
            borderLeft: '1px solid rgba(34,36,38,.15)',
          }}>
          {columnNames.map(columnName => {
            let columnKey = columnName.split(':')[1];
            if (columnName === 'Select') {
              return <Table.HeaderCell />;
            }
            return (
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
                  if (columnName === 'Runtime') {
                    return;
                  }
                  if (columnName === 'Ran') {
                    this.props.setSort(null, true);
                  } else {
                    let ascending = true;
                    if (sort.name === columnName) {
                      ascending = !sort.ascending;
                    }
                    this.props.setSort(columnName, ascending);
                  }
                }}>
                <div>
                  {_.startsWith(columnName, 'config:') ||
                  _.startsWith(columnName, 'summary:') ? (
                    columnKey.length > maxColNameLength ? (
                      <span key={columnName}>
                        {truncateString(columnKey, maxColNameLength)}
                      </span>
                    ) : (
                      <span>{columnKey}</span>
                    )
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
            );
          })}
        </Table.Row>
      </Table.Header>
    );
  }
}

class RunFeedSubgroups extends React.Component {
  render() {
    const runs = this.props.data.filtered;
    return runs.map((run, index) => (
      <Table.Row>
        {this.props.columnNames.map(
          columnName =>
            columnName === 'Description' ? (
              index === 0 && (
                <RunFeedDescription rowSpan={runs.length} {...this.props} />
              )
            ) : (
              <RunFeedCell columnName={columnName} run={run} />
            )
        )}
      </Table.Row>
    ));
    return <div>Run COUNT: {this.props.data.filtered.length}</div>;
  }
}

RunFeedSubgroups = withRunsDataLoader(RunFeedSubgroups);

class RunFeedGroupRow extends React.Component {
  state = {};

  render() {
    let {run, loading, columnNames, project} = this.props;
    if (!this.state.subgroupOpen) {
      return (
        <RunFeedRunRow
          {...this.props}
          subgroupClick={() => this.setState({subgroupOpen: true})}
          runsClick={() => this.setState({runsOpen: true})}
          subgroupsClosed={!this.state.subGroupOpen}
          runsClosed={!this.state.runsOpen}
        />
      );
    } else {
      let query = _.cloneDeep(this.props.query);
      query.filters = {
        key: {section: 'config', name: this.props.query.grouping.group},
        op: '=',
        value: run.config[this.props.query.grouping.group],
      };
      query.level = 'subgroup';
      console.log('USING QUERY', query);
      return (
        <RunFeedSubgroups
          subgroupClick={() => this.setState({subgroupOpen: false})}
          {...this.props}
          query={query}
        />
      );
    }
  }
}

class RunFeedRunRow extends React.Component {
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

  render() {
    let {run, loading, columnNames, project} = this.props;
    const summary = run.summary;
    const config = run.config;
    const selected =
      this.props.selections && Filter.match(this.props.selections, run);
    return (
      <Table.Row key={run.id}>
        {columnNames.map(columnName => (
          <RunFeedCell columnName={columnName} {...this.props} />
        ))}
      </Table.Row>
    );
  }
}

class RunFeed extends PureComponent {
  state = {pageLoading: true};

  static defaultProps = {
    currentPage: 1,
  };
  state = {sort: 'timeline', dir: 'descending'};

  handleScroll() {
    if (this.props.loading || this.state.pageLoading) {
      return;
    }
    const windowHeight =
      'innerHeight' in window
        ? window.innerHeight
        : document.documentElement.offsetHeight;
    const body = document.body;
    const html = document.documentElement;
    const docHeight = Math.max(
      body.scrollHeight,
      body.offsetHeight,
      html.clientHeight,
      html.scrollHeight,
      html.offsetHeight
    );
    const windowBottom = windowHeight + window.pageYOffset;
    if (windowBottom >= docHeight) {
      if (this.props.data.loadMore) {
        this.setState({pageLoading: true});
        this.props.data.loadMore(() => {
          this.setState({pageLoading: false});
        });
      }
    }
  }

  componentDidMount() {
    // window.addEventListener('scroll', () => this.handleScroll());
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillUnmount() {
    // window.removeEventListener('scroll', () => this.handleScroll());
  }

  componentDidUpdate() {
    // setTimeout(() => this.handleScroll(), 1);
  }

  _setup(props) {
    this.columnNames =
      props.data.length === 0 && props.loading
        ? ['Description']
        : getColumns(props.data.filtered);
  }

  componentWillReceiveProps(nextProps) {
    if (
      this.props.data.filtered !== nextProps.data.filtered ||
      this.props.loading !== nextProps.loading
    ) {
      this._setup(nextProps);
    }
  }

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

  render() {
    const runsLength = this.props.runCount;
    let runs = this.props.data.filtered;
    if (!this.props.loading && runsLength === 0) {
      return (
        <div style={{marginTop: 30}}>No runs match the chosen filters.</div>
      );
    }
    if (this.props.groupKey) {
      let groupedRuns = [];
      let group = [];
      let prevGroupName = '<doesntexist>';
      for (const run of runs) {
        const groupName = run.config[this.props.groupKey];
        if (groupName !== prevGroupName && group.length > 0) {
          groupedRuns.push(group);
          group = [];
        }
        group.push(run);
        prevGroupName = groupName;
      }
      groupedRuns.push(group);
      runs = groupedRuns;
    }
    return (
      <div>
        <div className="runsTable">
          <Table
            definition
            style={{borderLeft: null}}
            celled
            sortable
            compact
            unstackable
            size="small">
            <RunFeedHeader
              sort={this.props.sort}
              setSort={this.props.setSort}
              columnNames={this.columnNames}
            />
            <Table.Body>
              {(this.state.pageLoading || !this.props.loading) &&
                runs &&
                runs.map(
                  (run, i) =>
                    this.props.query.level != 'run' ? (
                      <RunFeedGroupRow
                        key={i}
                        // groupName={run[0].config[this.props.groupKey]}
                        run={run}
                        loading={false}
                        selections={this.props.selections}
                        columnNames={this.columnNames}
                        project={this.props.project}
                        addFilter={(type, key, op, value) =>
                          this.props.setFilters(
                            type,
                            Filter.Update.groupPush(this.props.filters, [0], {
                              key,
                              op,
                              value,
                            })
                          )
                        }
                        query={this.props.query}
                        setFilters={this.props.setFilters}
                      />
                    ) : (
                      <RunFeedRunRow
                        key={i}
                        run={run}
                        loading={false}
                        selections={this.props.selections}
                        columnNames={this.columnNames}
                        project={this.props.project}
                        addFilter={(type, key, op, value) =>
                          this.props.setFilters(
                            type,
                            Filter.Update.groupPush(this.props.filters, [0], {
                              key,
                              op,
                              value,
                            })
                          )
                        }
                        setFilters={this.props.setFilters}
                      />
                    )
                )}
              {this.props.loading && (
                <RunFeedRunRow
                  selections={this.props.selections}
                  key="loader"
                  run={{config: {}, summary: {}}}
                  loading={true}
                  columnNames={this.columnNames}
                />
              )}
            </Table.Body>
          </Table>
        </div>
        <Button content="Load More" onClick={() => this.handleScroll()} />
      </div>
    );
  }
}

function mapStateToProps() {
  let prevColumns = null;
  let prevRuns = null;
  let cols = {};
  let autoCols = {};

  return function(state, ownProps) {
    const id = ownProps.project.id;
    return {
      columns: cols,
      sort: state.runs.sort,
      currentPage: state.runs.pages[id] && state.runs.pages[id].current,
      selections: state.runs.filters.select,
      filters: state.runs.filters.filter,
    };
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({setFilters, setSort}, dispatch);
};

// export dumb component for testing purposes
export {RunFeed};

export default withRunsDataLoader(
  connect(mapStateToProps(), mapDispatchToProps)(RunFeed)
);
