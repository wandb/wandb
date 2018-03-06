import React from 'react';
import {graphql} from 'react-apollo';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {Container, Loader} from 'semantic-ui-react';
import update from 'immutability-helper';
import Dashboards from '../components/Dashboards';
import DashboardView from '../components/DashboardView';
import ViewModifier from '../containers/ViewModifier';
import ErrorPage from '../components/ErrorPage';
import withHistoryLoader from '../containers/HistoryLoader';
import {MODEL_QUERY, MODEL_UPSERT} from '../graphql/models';
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
import {setServerViews, setActiveView} from '../actions/view';
import {addFilter} from '../actions/run';
import {updateLocationParams} from '../actions/location';
import withRunsDataLoader from '../containers/RunsDataLoader';
import withRunsQueryRedux from '../containers/RunsQueryRedux';

class Dashboard extends React.Component {
  ensureModel() {
    return this.props.loading || (this.props.model && this.props.model.name);
  }

  componentWillMount() {
    this.props.updateLocationParams(this.props.match.params);
    this.props.addFilter('select', {section: 'run', value: 'id'}, '=', '*');
  }

  componentWillReceiveProps(nextProps) {
    // Setup views loaded from server.
    if (
      nextProps.data.base.length > 0 &&
      (nextProps.views === null || !nextProps.views.dashboards) &&
      _.isEmpty(this.props.reduxServerViews.dashboards.views) &&
      _.isEmpty(this.props.reduxBrowserViews.dashboards.views)
    ) {
      // no views on server, provide a default
      this.props.setServerViews(
        defaultViews((nextProps.buckets.edges[0] || {}).node),
        true,
      );
    } else if (
      nextProps.views &&
      nextProps.views.dashboards &&
      _.isEqual(this.props.reduxServerViews, this.props.reduxBrowserViews) &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      this.props.setServerViews(nextProps.views);
    }
  }

  render() {
    let action = this.props.match.path.split('/').pop();
    return (
      <Container fluid style={{padding: '0 20px'}}>
        {this.props.loading ? (
          <Loader active={this.props.loading} size="massive" />
        ) : (
          <ViewModifier
            {...this.props}
            component={Dashboards}
            viewComponent={DashboardView}
            editMode={this.props.user && action === 'edit'}
            viewType="dashboards"
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
        )}
      </Container>
    );
  }
}

const withMutations = graphql(MODEL_UPSERT, {
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
});

// export dumb component for testing purposes
//export {Dashboard};

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

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {addFilter, setServerViews, setActiveView, updateLocationParams},
    dispatch,
  );
};

Dashboard = withMutations(
  withRunsQueryRedux(
    withRunsDataLoader(connect(mapStateToProps, mapDispatchToProps)(Dashboard)),
  ),
);

class DashboardWrapper extends React.Component {
  render() {
    var {match} = this.props;
    return (
      <Dashboard
        {...this.props}
        histQueryKey="dashboardsPage"
        match={match}
        query={{
          entity: match.params.entity,
          model: match.params.model,
          strategy: 'merge',
        }}
      />
    );
  }
}

export default DashboardWrapper;
