import React, {PureComponent} from 'react';
import {
  Button,
  Checkbox,
  Icon,
  Image,
  Table,
  Item,
  Loader,
  Popup,
} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import {NavLink} from 'react-router-dom';
import './RunFeed.css';
import Launcher from '../containers/Launcher';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {
  addFilter,
  enableColumn,
  toggleRunSelection,
  setSort,
} from '../actions/run';
import _ from 'lodash';
import {JSONparseNaN} from '../util/jsonnan';
import Pagination from './Pagination';
import numeral from 'numeral';
import {
  displayValue,
  getRunValue,
  sortableValue,
  filterRuns,
} from '../util/runhelpers.js';
import ContentLoader from 'react-content-loader';

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
                <span className="value">
                  {displayValue(this.props.value)}
                </span>{' '}
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

class RunFeed extends PureComponent {
  static defaultProps = {
    currentPage: 1,
  };
  state = {sort: 'timeline', dir: 'descending', best: {}, confCounts: {}};
  stateToIcon(state) {
    let icon = 'check',
      color = 'green';
    if (state === 'failed') {
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

  componentWillReceiveProps(nextProps) {
    //for (var prop of _.keys(nextProps)) {
    //  console.log('prop equal?', prop, this.props[prop] === nextProps[prop]);
    //}
    if (nextProps.runs) {
      let best = {};
      let confCounts = {};
      let total = 0;
      nextProps.runs.forEach((run, i) => {
        const summaryMetrics = run.summaryMetrics || {},
          config = run.config || {};
        Object.keys(config).forEach(key => {
          confCounts[key] = confCounts[key] || {};
          confCounts[key][config[key]] =
            (confCounts[key][config[key]] || 0) + 1;
        });
        best = {...summaryMetrics};
        total += 1;
        Object.keys(summaryMetrics).forEach(key => {
          best[key] = best[key] || {val: summaryMetrics[key], i};
          let better =
            this.state.dir === 'ascending'
              ? best[key].val <= summaryMetrics[key]
              : best[key].val > summaryMetrics[key];
          if (better) {
            best[key] = {val: summaryMetrics[key], i};
          }
        });
      });
      //Ignore things that change every time
      Object.keys(confCounts).forEach(key => {
        Object.keys(confCounts[key]).forEach(val => {
          if (confCounts[key][val] >= total) {
            confCounts[key][val] = 1;
          }
        });
      });
      this.setState({best, confCounts});
    }
  }

  bestConfig(config) {
    const best = Object.keys(config)
      .sort()
      .sort((a, b) => {
        return (
          Object.keys(this.state.confCounts[b] || {}).length -
          Object.keys(this.state.confCounts[a] || {}).length
        );
      });
    return best; //.slice(0, 3);
  }

  tablePlaceholders(limit, length) {
    let pageLength = !length || length > limit ? limit : length;
    return Array.from({length: pageLength}).map((x, i) => {
      return {id: i};
    });
  }

  descriptionCell(edge, props) {
    return (
      <Table.Cell className="overview" key="Description">
        {this.props.loading && (
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
        {!this.props.loading && (
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
                    to={`/${props.project.entityName}/${props.project
                      .name}/runs/${edge.name}`}>
                    {edge.description || edge.name ? (
                      (edge.description || edge.name).split('\n')[0]
                    ) : (
                      ''
                    )}{' '}
                    {this.stateToIcon(edge.state)}
                  </NavLink>
                </Item.Header>
                <Item.Extra style={{marginTop: 0}}>
                  <strong>{edge.user && edge.user.username}</strong>
                  {/* edge.host && `on ${edge.host} ` */}
                  {/*edge.fileCount + ' files saved' NOTE: to add this back, add fileCount back to RUNS_QUERY*/}
                </Item.Extra>
                {props.admin && (
                  <Launcher runId={edge.id} runName={edge.name} />
                )}
              </Item.Content>
            </Item>
          </Item.Group>
        )}
      </Table.Cell>
    );
  }

  render() {
    let lastDay = 0,
      stats =
        this.props.project &&
        Object.keys(JSONparseNaN(this.props.project.summaryMetrics)).sort(),
      runsLength = this.props.runs && this.props.runs.length,
      startIndex = (this.props.currentPage - 1) * this.props.limit,
      endIndex = Math.min(startIndex + this.props.limit, runsLength),
      runs =
        this.props.runs && this.props.runs.length > 0 && !this.props.loading
          ? this.props.runs.slice(startIndex, endIndex)
          : this.tablePlaceholders(
              this.props.limit,
              this.props.project.bucketCount,
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
            <Table.Header>
              <Table.Row>
                {this.props.selectable && <Table.HeaderCell />}
                {this.props.columnNames
                  .filter(columnName => this.props.columns[columnName])
                  .map(columnName => (
                    <Table.HeaderCell
                      key={columnName}
                      className={
                        _.startsWith(columnName, 'config:') ||
                        _.startsWith(columnName, 'summary:') ? (
                          'rotate'
                        ) : (
                          ''
                        )
                      }
                      style={{textAlign: 'center', verticalAlign: 'bottom'}}
                      onClick={() => {
                        if (columnName == 'Config' || columnName == 'Summary') {
                          return;
                        }
                        let ascending = true;
                        if (this.props.sort.name == columnName) {
                          ascending = !this.props.sort.ascending;
                        }
                        this.props.setSort(columnName, ascending);
                      }}>
                      <div>
                        <span>
                          {_.startsWith(columnName, 'config:') ||
                          _.startsWith(columnName, 'summary:') ? (
                            columnName.split(':')[1]
                          ) : (
                            columnName
                          )}
                          {this.props.sort.name == columnName &&
                            (this.props.sort.ascending ? (
                              <Icon name="caret up" />
                            ) : (
                              <Icon name="caret down" />
                            ))}
                        </span>
                      </div>
                    </Table.HeaderCell>
                  ))}
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {runs &&
                runs.map((run, i) => {
                  //TODO: this should always be an object
                  const summary = run.summary;
                  const config = run.config;
                  let event = (
                    <Table.Row key={run.id}>
                      {this.props.selectable && (
                        <Table.Cell collapsing>
                          <Checkbox
                            checked={!!this.props.selectedRuns[run.name]}
                            onChange={() =>
                              this.props.toggleRunSelection(run.name, run.id)}
                          />
                        </Table.Cell>
                      )}
                      {(this.props.loading
                        ? ['Description']
                        : this.props.columnNames)
                        .filter(
                          columnName =>
                            this.props.loading
                              ? true
                              : this.props.columns[columnName],
                        )
                        .map(columnName => {
                          if (columnName == 'Description') {
                            return this.descriptionCell(run, this.props);
                          } else if (columnName == 'Sweep') {
                            return (
                              <Table.Cell key="stop" collapsing>
                                {run.sweep && (
                                  <ValueDisplay
                                    section="sweep"
                                    valKey="name"
                                    value={run.sweep.name}
                                    content={
                                      <NavLink
                                        to={`/${this.props.project
                                          .entityName}/${this.props.project
                                          .name}/sweeps/${run.sweep.name}`}>
                                        {run.sweep.name}
                                      </NavLink>
                                    }
                                  />
                                )}
                              </Table.Cell>
                            );
                          } else if (columnName == 'Ran') {
                            return (
                              <Table.Cell key={columnName} collapsing>
                                <TimeAgo date={run.createdAt + 'Z'} />
                              </Table.Cell>
                            );
                          } else if (columnName == 'Runtime') {
                            return (
                              <Table.Cell key={columnName} collapsing>
                                {run.heartbeatAt && (
                                  <TimeAgo
                                    date={run.createdAt + 'Z'}
                                    now={() => {
                                      return Date.parse(run.heartbeatAt + 'Z');
                                    }}
                                    formatter={(v, u, s, d, f) =>
                                      f().replace(s, '')}
                                    live={false}
                                  />
                                )}
                              </Table.Cell>
                            );
                          } else if (columnName == 'Config') {
                            return (
                              <Table.Cell
                                className="config"
                                key={columnName}
                                collapsing>
                                <div>
                                  {config &&
                                    this.bestConfig(config)
                                      .slice(0, 20)
                                      .map(k => (
                                        <ValueDisplay
                                          section="config"
                                          key={k}
                                          valKey={k}
                                          value={config[k]}
                                          enablePopout
                                        />
                                      ))}
                                </div>
                              </Table.Cell>
                            );
                          } else if (columnName == 'Summary') {
                            return (
                              <Table.Cell
                                className="config"
                                key={columnName}
                                collapsing>
                                <div>
                                  {_.keys(summary)
                                    .slice(0, 20)
                                    .map(k => (
                                      <ValueDisplay
                                        section="summary"
                                        key={k}
                                        valKey={k}
                                        value={summary[k]}
                                        enablePopout
                                      />
                                    ))}
                                </div>
                              </Table.Cell>
                            );
                          } else if (columnName == 'Stop') {
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
                  return event;
                })}
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
  for (var key of allKeys) {
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

  return function(state, ownProps) {
    const id = ownProps.project.id;
    if (state.runs.columns !== prevColumns || ownProps.runs !== prevRuns) {
      prevColumns = state.runs.columns;
      prevRuns = ownProps.runs;
      if (state.runs.columns['_ConfigAuto']) {
        let autoCols = autoConfigCols(ownProps.runs);
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
