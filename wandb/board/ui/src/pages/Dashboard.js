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
import {MODEL_QUERY, MODEL_UPSERT} from '../graphql/models';

class Dashboard extends React.Component {
  ensureModel() {
    return this.props.loading || (this.props.model && this.props.model.name);
  }

  updateDimensions = () => {
    this.setState({
      width: Math.max(640, window.innerWidth),
      height: window.innerHeight,
    });
  };

  componentWillMount() {
    this.updateDimensions();
  }

  componentDidMount() {
    window.addEventListener('resize', this.updateDimensions);
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.updateDimensions);
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
            {...this.state}
            component={Dashboards}
            viewComponent={DashboardView}
            editMode={this.props.user && action === 'edit'}
            viewType="dashboards"
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

const withData = graphql(MODEL_QUERY, {
  options: ({match: {params, path}, user}) => {
    return {
      variables: {
        entityName: params.entity || 'board',
        name: params.model || 'default',
        bucketName: params.bucket || 'latest',
        detailed: false,
      },
    };
  },
  props: ({data: {loading, model, viewer}}) => {
    return {
      loading,
      model,
      viewer,
      data: model && model.views.dashboards && model.views.dashboards[0],
    };
  },
});

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
export {Dashboard};

export default withMutations(withData(Dashboard));
