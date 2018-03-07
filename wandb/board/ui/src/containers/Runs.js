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
import RunFiltersRedux from './RunFiltersRedux';
import RunColumnsSelector from '../components/RunColumnsSelector';
import ViewModifier from './ViewModifier';
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
  parseBuckets,
  setupKeySuggestions,
} from '../util/runhelpers.js';
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import {bindActionCreators} from 'redux';
import {clearFilters, addFilter, setColumns} from '../actions/run';
import {setServerViews, setBrowserViews, setActiveView} from '../actions/view';
import update from 'immutability-helper';
import {BOARD} from '../util/board';
import withRunsDataLoader from '../containers/RunsDataLoader';
import withRunsQueryRedux from '../containers/RunsQueryRedux';

class Runs extends React.Component {
  state = {showFailed: false, activeTab: 0, showFilters: false};

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  onSort = (column, order = 'descending') => {
    this.props.refetch({order: [column, order].join(' ')});
  };

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
    this._readUrl(this.props);
  }

  componentDidMount() {
    this.doneLoading = false;

    this._setUrl({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    console.log('RUNS nextProps', nextProps);
    if (
      !this.doneLoading &&
      nextProps.loading === false &&
      nextProps.data.base.length > 0
    ) {
      this.doneLoading = true;
      let defaultColumns = {
        Description: true,
        Ran: true,
        Runtime: true,
        _ConfigAuto: true,
        Sweep: _.indexOf(nextProps.data.columnNames, 'Sweep') !== -1,
      };
      let summaryColumns = nextProps.data.columnNames.filter(col =>
        _.startsWith(col, 'summary'),
      );
      for (var col of summaryColumns) {
        defaultColumns[col] = true;
      }
      this.props.setColumns(defaultColumns);
    }
    // Setup views loaded from server.
    if (
      nextProps.data.base.length > 0 &&
      (nextProps.views === null || !nextProps.views.runs) &&
      _.isEmpty(this.props.reduxServerViews.runs.views) &&
      _.isEmpty(this.props.reduxBrowserViews.runs.views)
    ) {
      // no views on server, provide a default
      this.props.setBrowserViews(
        defaultViews((nextProps.buckets.edges[0] || {}).node),
      );
    } else if (
      nextProps.views &&
      nextProps.views.runs &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      if (
        _.isEqual(this.props.reduxServerViews, this.props.reduxBrowserViews)
      ) {
        this.props.setBrowserViews(nextProps.views);
      }
      this.props.setServerViews(nextProps.views);
    }
    this._setUrl(this.props, nextProps);
  }

  handleTabChange = (e, {activeIndex}) =>
    this.setState({activeTab: activeIndex});

  render() {
    console.log('Runs props!', this.props);
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
                {this.props.data.base.length} total runs,{' '}
                {this.props.data.filtered.length} filtered,{' '}
                {this.props.data.selectedRuns.length} selected
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
                      <RunFiltersRedux
                        kind="filter"
                        buttonText="Add Filter"
                        keySuggestions={this.props.data.keys}
                        runs={this.props.data.base}
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
                      <RunFiltersRedux
                        kind="select"
                        buttonText="Add Selection"
                        keySuggestions={this.props.data.keys}
                        runs={this.props.data.base}
                      />
                    </Grid.Column>
                  </Grid.Row>
                )}
              </Transition.Group>
            </Grid.Column>
          </Grid.Row>
          <Grid.Column width={16}>
            <ViewModifier
              viewType="runs"
              data={this.props.data}
              pageQuery={this.props.query}
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
          runs={this.props.data.filtered}
          project={this.props.model}
          onSort={this.onSort}
          showFailed={this.state.showFailed}
          selectable={true}
          selectedRuns={this.props.data.selectedRunsById}
          columnNames={this.props.data.columnNames}
          limit={this.props.limit}
        />
      </Container>
    );
  }
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
    {
      setColumns,
      clearFilters,
      addFilter,
      setServerViews,
      setBrowserViews,
      setActiveView,
    },
    dispatch,
  );
};

export default connect(mapStateToProps, mapDispatchToProps)(
  withMutations(withRunsQueryRedux(withRunsDataLoader(Runs))),
);
