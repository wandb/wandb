import React from 'react';
import {graphql} from 'react-apollo';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {Container} from 'semantic-ui-react';
import update from 'immutability-helper';
import TabbedViews from '../components/TabbedViews';
import DashboardView from '../components/DashboardView';
import ViewModifier from '../containers/ViewModifier';
import Loader from '../components/Loader';
import withHistoryLoader from '../containers/HistoryLoader';
import {MODEL_QUERY, MODEL_UPSERT} from '../graphql/models';
import {PROJECT_QUERY} from '../graphql/runs';
import {
  sortRuns,
  defaultViews,
  parseBuckets,
  setupKeySuggestions,
} from '../util/runhelpers.js';
import {setServerViews, setBrowserViews, setActiveView} from '../actions/view';
import {setFilters} from '../actions/run';
import {updateLocationParams} from '../actions/location';
import withRunsDataLoader from '../containers/RunsDataLoader';
import withRunsQueryRedux from '../containers/RunsQueryRedux';
import _ from 'lodash';
import * as Filter from '../util/filters';
import * as Select from '../util/selections';

class Dashboard extends React.Component {
  ensureModel() {
    return this.props.loading || (this.props.model && this.props.model.name);
  }

  componentWillMount() {
    this.props.updateLocationParams(this.props.match.params);
    this.props.setFilters('filter', {
      op: 'OR',
      filters: [
        {
          op: 'AND',
          filters: [],
        },
      ],
    });
    this.props.setFilters('select', Select.all());
  }

  componentWillReceiveProps(nextProps) {
    // Setup views loaded from server.
    if (
      !nextProps.loading &&
      nextProps.views === null &&
      _.isEmpty(this.props.reduxServerViews.dashboards.views) &&
      _.isEmpty(this.props.reduxBrowserViews.dashboards.views)
    ) {
      // no views on server, provide a default
      this.props.setBrowserViews(defaultViews());
    }
    if (
      nextProps.views &&
      nextProps.views.dashboards &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      if (
        _.isEqual(this.props.reduxServerViews, this.props.reduxBrowserViews)
      ) {
        this.props.setBrowserViews(nextProps.views);
      }
      this.props.setServerViews(nextProps.views);
    }
  }

  render() {
    let action = this.props.match.path.split('/').pop();
    return (
      <Container fluid style={{padding: '0 20px'}}>
        {this.props.loading ? (
          <Loader />
        ) : (
          <ViewModifier
            {...this.props}
            component={TabbedViews}
            viewComponent={DashboardView}
            editMode={this.props.user && action === 'edit'}
            viewType="dashboards"
            data={this.props.data}
            pageQuery={{
              entity: this.props.match.params.entity,
              model: this.props.match.params.model,
              sort: this.props.sort,
              filters: this.props.runFilters,
              selections: this.props.runSelections,
            }}
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
    activeView: state.views.other.dashboards.activeView,
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {
      setFilters,
      setServerViews,
      setBrowserViews,
      setActiveView,
      updateLocationParams,
    },
    dispatch
  );
};

const withData = graphql(PROJECT_QUERY, {
  options: ({match, runFilters, runSelections}) => {
    return {
      variables: {
        entityName: match.params.entity,
        name: match.params.model,
        filters: JSON.stringify(Filter.toMongo(runFilters)),
        selections: JSON.stringify(
          Filter.toMongo(Filter.And([runFilters, runSelections]))
        ),
      },
    };
  },
  props: ({data: {loading, project, viewer, fetchMore}, errors}) => {
    //TODO: For some reason the first poll causes loading to be true
    // if (project && projects.runs && loading) loading = false;
    return {
      loading,
      views: project && project.views && JSON.parse(project.views),
      projectID: project && project.id,
    };
  },
});

Dashboard = withMutations(
  withRunsQueryRedux(
    connect(mapStateToProps, mapDispatchToProps)(withData(Dashboard))
  )
);

class DashboardWrapper extends React.Component {
  render() {
    var {match} = this.props;
    return <Dashboard {...this.props} match={match} />;
  }
}

// export dumb component for testing purposes
export {Dashboard};

export default DashboardWrapper;
