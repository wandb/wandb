import React from 'react';
import {graphql, compose} from 'react-apollo';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import update from 'immutability-helper';
import {Container, Loader} from 'semantic-ui-react';
import ModelEditor from '../components/ModelEditor';
import ModelViewer from '../components/ModelViewer';
import {MODEL_QUERY, MODEL_DELETION, MODEL_UPSERT} from '../graphql/models';
import {updateLocationParams} from '../actions/location';

let Sweeps;
try {
  Sweeps = require('Cloud/components/Sweeps').default;
} catch (e) {}

class Model extends React.Component {
  componentWillMount() {
    this.props.updateLocationParams(this.props.match.params);
  }

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  ensureModel() {
    return this.props.loading || (this.props.model && this.props.model.name);
  }

  render() {
    let action = this.props.match.path.split('/').pop();
    return (
      <Container className="model">
        {this.props.loading ? (
          <Loader active={this.props.loading} size="massive" />
        ) : this.props.user && action === 'edit' ? (
          <ModelEditor {...this.props} />
        ) : this.props.user && action === 'sweeps' ? (
          <Sweeps {...this.props} />
        ) : (
          <ModelViewer {...this.props} />
        )}
      </Container>
    );
  }
}

const withData = graphql(MODEL_QUERY, {
  options: ({match: {params, path}, user}) => {
    return {
      variables: {
        entityName: params.entity,
        // name: params.model,
        bucketName: params.bucket || 'latest',
        upload: user && path.split('/').pop() === 'edit' ? true : false,
        detailed: false,
      },
    };
  },
  props: ({data: {loading, model, viewer, error}, errors}) => {
    return {
      loading,
      model,
      error,
      viewer,
    };
  },
});

const withMutations = compose(
  graphql(MODEL_DELETION, {
    props: ({mutate}) => ({
      delete: id =>
        mutate({
          variables: {id},
        }).then(() => (window.location.href = '/')),
    }),
  }),
  graphql(MODEL_UPSERT, {
    props: ({mutate}) => ({
      submit: variables =>
        mutate({
          variables: {...variables},
          updateQueries: {
            Model: (prev, {mutationResult}) => {
              const newModel = mutationResult.data.upsertModel.model;
              return update(prev, {model: newModel});
            },
          },
        }),
    }),
  })
);

const modelMapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({updateLocationParams}, dispatch);
};

// Model = connect(null, modelMapDispatchToProps)(Model);

// export dumb component for testing purposes
export {Model};

export default withMutations(
  withData(connect(null, modelMapDispatchToProps)(Model))
);
