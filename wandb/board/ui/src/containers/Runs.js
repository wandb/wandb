import React from 'react';
import {graphql, compose, withApollo} from 'react-apollo';
import {
  Container,
  Button,
  Grid,
  Icon,
  Popup,
  Transition,
} from 'semantic-ui-react';
import RunFeed from '../components/RunFeed';
import RunFilters from '../components/RunFilters';
import RunColumnsSelector from '../components/RunColumnsSelector';
import withHistoryLoader from '../components/HistoryLoader';
import Views from '../components/Views';
import HelpIcon from '../components/HelpIcon';
import {RUNS_QUERY} from '../graphql/runs';
import {MODEL_UPSERT} from '../graphql/models';
import {connect} from 'react-redux';
import queryString from 'query-string';
import _ from 'lodash';
import {
  filterRuns,
  sortRuns,
  filterToString,
  filterFromString,
  displayFilterKey,
  defaultViews,
} from '../util/runhelpers.js';
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import {bindActionCreators} from 'redux';
import {clearFilters, addFilter, setColumns} from '../actions/run';
import {setServerViews, setActiveView} from '../actions/view';
import {JSONparseNaN} from '../util/jsonnan';
import update from 'immutability-helper';
import flatten from 'flat';
import {BOARD} from '../util/board';

class Runs extends React.Component {
  state = {showFailed: false, activeTab: 0, showFilters: false};

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  onSort = (column, order = 'descending') => {
    this.props.refetch({order: [column, order].join(' ')});
  };

  _setupViewData(props) {
    this.viewData = {
      base: props.runs,
      filtered: this.filteredRuns,
      filteredRunsById: this.filteredRunsById,
      keys: props.keySuggestions,
      axisOptions: this.axisOptions,
      histories: this.runHistories,
    };
  }

  _setupFilteredRuns(props) {
    this.filteredRuns = sortRuns(
      props.sort,
      filterRuns(props.runFilters, props.runs),
    );
    this.filteredRunsById = {};
    for (var run of this.filteredRuns) {
      this.filteredRunsById[run.name] = run;
    }
    let keys = _.flatMap(props.keySuggestions, section => section.suggestions);
    this.axisOptions = keys.map(key => {
      let displayKey = displayFilterKey(key);
      return {
        key: displayKey,
        value: displayKey,
        text: displayKey,
      };
    });
    this._setupViewData(props);
  }

  _setupRunHistories(props) {
    this.historyKeys = _.uniq(
      _.flatMap(
        _.uniq(
          _.flatMap(
            props.runHistory,
            o => (o.history ? o.history.map(row => _.keys(row)) : []),
          ),
        ),
      ),
    );
    this.runHistories = {
      loading: props.runHistory.some(o => !o.history),
      maxRuns: MAX_HISTORIES_LOADED,
      totalRuns: _.keys(props.selectedRuns).length,
      data: props.runHistory.filter(o => o.history),
      keys: this.historyKeys,
    };
    this._setupViewData(props);
  }

  _setUrl(props, nextProps) {
    if (
      props.runFilters !== nextProps.runFilters ||
      props.runSelections !== nextProps.runSelections ||
      props.activeView !== nextProps.activeView
    ) {
      let query = queryString.parse(window.location.search) || {};
      if (!_.isEmpty(nextProps.runFilters)) {
        query.filter = _.values(nextProps.runFilters).map(filterToString);
      }
      if (!_.isEmpty(nextProps.runSelections)) {
        query.select = _.values(nextProps.runSelections).map(filterToString);
      }
      if (!_.isNil(nextProps.activeView)) {
        query.activeView = nextProps.activeView;
      }
      let url = `/${nextProps.match.params.entity}/${
        nextProps.match.params.model
      }/runs`;
      if (!_.isEmpty(query)) {
        url += '?' + queryString.stringify(query);
      }
      window.history.replaceState(null, null, url);
    }
  }

  _readUrl(props) {
    var parsed = queryString.parse(window.location.search);
    if (!parsed) {
      return;
    }
    let readFilters = kind => {
      if (parsed[kind]) {
        if (!_.isArray(parsed[kind])) {
          parsed[kind] = [parsed[kind]];
        }
        let filters = parsed[kind].map(filterFromString);
        filters = filters.filter(filter => filter);
        for (var filter of filters) {
          this.props.addFilter(kind, filter.key, filter.op, filter.value);
        }
        return filters;
      }
      return [];
    };
    readFilters('filter');
    let selectFilters = readFilters('select');
    if (selectFilters.length === 0) {
      this.props.addFilter('select', {section: 'run', value: 'id'}, '=', '*');
    }
    if (!_.isNil(parsed.activeView)) {
      this.props.setActiveView('runs', parseInt(parsed.activeView, 10));
    }
  }

  componentWillMount() {
    this.props.clearFilters();
    this._setupFilteredRuns(this.props);
    this._setupRunHistories(this.props);
    this._readUrl(this.props);
  }

  componentDidMount() {
    this.doneLoading = false;

    this._setUrl({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    if (
      !this.doneLoading &&
      nextProps.loading === false &&
      nextProps.runs.length > 0
    ) {
      this.doneLoading = true;
      let defaultColumns = {
        Description: true,
        Ran: true,
        Runtime: true,
        _ConfigAuto: true,
        Sweep: _.indexOf(nextProps.columnNames, 'Sweep') !== -1,
      };
      let summaryColumns = nextProps.columnNames.filter(col =>
        _.startsWith(col, 'summary'),
      );
      for (var col of summaryColumns) {
        defaultColumns[col] = true;
      }
      this.props.setColumns(defaultColumns);
    }
    // Setup views loaded from server.
    if (
      (nextProps.views === null || !nextProps.views.runs) &&
      _.isEmpty(this.props.reduxServerViews.runs.views) &&
      _.isEmpty(this.props.reduxBrowserViews.runs.views)
    ) {
      // no views on server, provide a default
      this.props.setServerViews(
        defaultViews(nextProps.runs || this.props.runs),
        true,
      );
    } else if (
      nextProps.views &&
      nextProps.views.runs &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      this.props.setServerViews(nextProps.views);
    }

    if (
      nextProps.runFilters !== this.props.runFilters ||
      nextProps.runs !== this.props.runs ||
      nextProps.sort !== this.props.sort
    ) {
      this._setupFilteredRuns(nextProps);
    }
    if (nextProps.runHistory !== this.props.runHistory) {
      this._setupRunHistories(nextProps);
    }

    this._setUrl(this.props, nextProps);
  }

  handleTabChange = (e, {activeIndex}) =>
    this.setState({activeTab: activeIndex});

  render() {
    return (
      <Container>
        <Grid>
          <Grid.Row>
            <Grid.Column>
              <p
                style={{cursor: 'pointer'}}
                onClick={() =>
                  this.setState({showFilters: !this.state.showFilters})
                }>
                <Icon
                  rotated={this.state.showFilters ? null : 'counterclockwise'}
                  name="dropdown"
                />
                {_.keys(this.props.runFilters).length === 0 &&
                _.keys(this.props.runSelections).length === 0
                  ? 'Filters / Selections'
                  : _.keys(this.props.runFilters).length +
                    ' Filters / ' +
                    _.keys(this.props.runSelections).length +
                    ' Selections'}
              </p>
              <p>
                {this.props.runs.length} total runs, {this.filteredRuns.length}{' '}
                filtered, {_.keys(this.props.selectedRuns).length} selected
              </p>
            </Grid.Column>
          </Grid.Row>
          <Grid.Row>
            <Grid.Column>
              <Transition.Group
                className="ui grid"
                animation="slide right"
                duration={200}>
                {this.state.showFilters && (
                  <Grid.Row>
                    <Grid.Column width={16}>
                      <h5 style={{marginBottom: 6}}>
                        Filters{' '}
                        <HelpIcon text="Filters limit the set of runs that will be displayed in charts and tables on this page." />
                      </h5>
                      <RunFilters
                        kind="filter"
                        buttonText="Add Filter"
                        keySuggestions={this.props.keySuggestions}
                        runs={this.props.runs}
                      />
                    </Grid.Column>
                  </Grid.Row>
                )}
                {this.state.showFilters && (
                  <Grid.Row>
                    <Grid.Column width={16}>
                      <h5 style={{marginBottom: 6}}>
                        Selections
                        <HelpIcon text="Selections control highlighted regions on charts, the runs displayed on History charts, and which runs are checked in the table." />
                      </h5>
                      <RunFilters
                        kind="select"
                        buttonText="Add Selection"
                        keySuggestions={this.props.keySuggestions}
                        runs={this.props.runs}
                      />
                    </Grid.Column>
                  </Grid.Row>
                )}
              </Transition.Group>
            </Grid.Column>
          </Grid.Row>
          <Grid.Column width={16}>
            <Views
              viewType="runs"
              data={this.viewData}
              updateViews={views =>
                this.props.updateModel({
                  entityName: this.props.match.params.entity,
                  name: this.props.match.params.model,
                  id: this.props.projectID,
                  views: views,
                })
              }
            />
          </Grid.Column>
          <Grid.Column width={16} style={{zIndex: 2}}>
            <Popup
              trigger={
                <Button floated="right" icon="columns" content="Columns" />
              }
              content={
                <RunColumnsSelector columnNames={this.props.columnNames} />
              }
              on="click"
              position="bottom left"
            />
          </Grid.Column>
        </Grid>
        <RunFeed
          admin={this.props.user && this.props.user.admin}
          loading={this.props.loading}
          runs={this.filteredRuns}
          project={this.props.model}
          onSort={this.onSort}
          showFailed={this.state.showFailed}
          selectable={true}
          selectedRuns={this.props.selectedRuns}
          columnNames={this.props.columnNames}
          limit={this.props.limit}
        />
      </Container>
    );
  }
}

function parseBuckets(buckets) {
  if (!buckets) {
    return [];
  }
  return buckets.edges.map(edge => {
    {
      let node = {...edge.node};
      node.config = node.config ? JSONparseNaN(node.config) : {};
      node.config = flatten(_.mapValues(node.config, confObj => confObj.value));
      node.summary = flatten(node.summaryMetrics)
        ? JSONparseNaN(node.summaryMetrics)
        : {};
      delete node.summaryMetrics;
      return node;
    }
  });
}

function getColumns(runs) {
  let configColumns = _.uniq(
    _.flatMap(runs, run => _.keys(run.config)).sort(),
  ).map(col => 'config:' + col);
  let summaryColumns = _.uniq(
    _.flatMap(runs, run => _.keys(run.summary)).sort(),
  ).map(col => 'summary:' + col);
  let sweepColumns =
    runs && runs.findIndex(r => r.sweep) > -1 ? ['Sweep', 'Stop'] : [];
  return ['Description'].concat(
    sweepColumns,
    ['Ran', 'Runtime', 'Config'],
    configColumns,
    ['Summary'],
    summaryColumns,
  );
}

function setupKeySuggestions(runs) {
  if (runs.length === 0) {
    return [];
  }

  let getSectionSuggestions = section => {
    let suggestions = _.uniq(_.flatMap(runs, run => _.keys(run[section])));
    suggestions.sort();
    return suggestions;
  };
  let runSuggestions = ['state', 'id'];
  let keySuggestions = [
    {
      title: 'run',
      suggestions: runSuggestions.map(suggestion => ({
        section: 'run',
        value: suggestion,
      })),
    },
    {
      title: 'sweep',
      suggestions: [{section: 'sweep', value: 'name'}],
    },
    {
      title: 'config',
      suggestions: getSectionSuggestions('config').map(suggestion => ({
        section: 'config',
        value: suggestion,
      })),
    },
    {
      title: 'summary',
      suggestions: getSectionSuggestions('summary').map(suggestion => ({
        section: 'summary',
        value: suggestion,
      })),
    },
  ];
  return keySuggestions;
}

function withData() {
  // This is a function so we can keep track of some state variables, and only change child props
  // when necessary for performance.
  let prevRuns = null;
  let runs = [];
  let columnNames = [];
  let keySuggestions = [];
  return graphql(RUNS_QUERY, {
    options: ({match: {params, path}, jobId, user, embedded}) => {
      const defaults = {
        variables: {
          jobKey: jobId,
          entityName: params.entity,
          name: params.model,
          order: 'timeline',
        },
      };
      if (BOARD) defaults.pollInterval = 5000;
      return defaults;
    },
    props: ({data: {loading, model, viewer, refetch}, errors}) => {
      //TODO: renaming extravaganza
      if (model && prevRuns !== model.buckets) {
        runs = parseBuckets(model.buckets);
        columnNames = getColumns(runs);
        keySuggestions = setupKeySuggestions(runs);
        prevRuns = model.buckets;
      }
      let views = null;
      if (model && model.views) {
        views = JSON.parse(model.views);
      }
      //TODO: For some reason the first poll causes loading to be true
      if (model && model.buckets && loading) loading = false;
      return {
        loading,
        refetch,
        projectID: model && model.id,
        buckets: model && model.buckets,
        views,
        runs,
        columnNames,
        keySuggestions,
        viewer,
      };
    },
  });
}

const withMutations = compose(
  graphql(MODEL_UPSERT, {
    props: ({mutate}) => ({
      updateModel: variables =>
        mutate({
          variables: {...variables},
          updateQueries: {
            Model: (prev, {mutationResult}) => {
              const newModel = mutationResult.data.upsertModel.model;
              return update(prev, {model: {$set: newModel}});
            },
          },
        }),
    }),
  }),
);

function mapStateToProps(state, ownProps) {
  return {
    jobId: state.runs.currentJob,
    runFilters: state.runs.filters.filter,
    runSelections: state.runs.filters.select,
    user: state.global.user,
    sort: state.runs.sort,
    filterModel: state.runs.filterModel,
    reduxServerViews: state.views.server,
    reduxBrowserViews: state.views.browser,
    activeView: state.views.other.runs.activeView,
  };
}

// export dumb component for testing purposes
export {Runs};

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {setColumns, clearFilters, addFilter, setServerViews, setActiveView},
    dispatch,
  );
};

export default connect(mapStateToProps, mapDispatchToProps)(
  withMutations(withData()(withHistoryLoader(withApollo(Runs)))),
);
