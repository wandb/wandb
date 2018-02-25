import React from 'react';
import {graphql, compose} from 'react-apollo';
import {Container, Loader} from 'semantic-ui-react';
import RunEditor from '../components/RunEditor';
import RunViewer from '../components/RunViewer';
import {MODEL_QUERY, MODEL_UPSERT} from '../graphql/models';
import {RUN_UPSERT, RUN_DELETION, RUN_STOP} from '../graphql/runs';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import update from 'immutability-helper';
import {setServerViews} from '../actions/view';
import {updateLocationParams} from '../actions/location';
import _ from 'lodash';
import {defaultViews} from '../util/runhelpers';
import {BOARD} from '../util/board';

class Run extends React.Component {
  state = {
    activeIndex: 0,
  };

  componentWillMount() {
    this.props.updateLocationParams(this.props.match.params);
  }

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  componentWillReceiveProps(nextProps) {
    // Setup views loaded from server.
    if (
      nextProps.bucket &&
      (nextProps.views === null || !nextProps.views.run) &&
      _.isEmpty(this.props.reduxServerViews.run.views) &&
      !this.props.reduxBrowserViews.run.configured
    ) {
      // no views on server, provide a default
      this.props.setServerViews(defaultViews(nextProps.bucket), true);
    } else if (
      nextProps.views &&
      nextProps.views.runs &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      this.props.setServerViews(nextProps.views);
    }
  }

  //TODO: why NOT this.props.model?
  render() {
    let action = this.props.match.path.split('/').pop();
    return (
      <Container>
        {this.props.loading || !this.props.model ? (
          <Loader size="massive" active={true} />
        ) : this.props.user && action === 'edit' ? (
          // TODO: Don't render button if user can't edit
          <RunEditor
            model={this.props.model}
            bucket={this.props.bucket}
            submit={this.props.submit}
          />
        ) : (
          <RunViewer
            onDelete={this.props.delete}
            onStop={this.props.stop}
            openFiles={e => {
              e.preventDefault();
              this.setState({activeIndex: 1});
            }}
            user={this.props.user}
            model={this.props.model}
            bucket={this.props.bucket}
            loss={this.props.loss}
            stream={this.props.stream}
            match={this.props.match}
            updateViews={views =>
              this.props.updateModel({
                entityName: this.props.match.params.entity,
                name: this.props.match.params.model,
                id: this.props.model.id,
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
  options: ({match: {params, path}}) => {
    const defaults = {
      variables: {
        entityName: params.entity,
        name: params.model,
        bucketName: params.run,
        detailed: true,
      },
    };
    if (BOARD) defaults.pollInterval = 2000;
    return defaults;
  },
  props: ({data, errors}) => {
    let views = null;
    if (data.model && data.model.views) {
      views = JSON.parse(data.model.views);
      if (BOARD && data.model.state === 'finished') data.stopPolling();
    }
    return {
      loading: data.loading,
      model: data.model,
      viewer: data.viewer,
      bucket: data.model && data.model.bucket,
      views: views,
    };
  },
});

const withMutations = compose(
  graphql(RUN_DELETION, {
    props: ({mutate}) => ({
      delete: id =>
        mutate({
          variables: {id},
        }).then(() => (window.location.href = '/')),
    }),
  }),
  graphql(RUN_STOP, {
    props: ({mutate}) => ({
      stop: id => {
        mutate({
          variables: {id},
        }).then(() => console.log('Stopping run'));
      },
    }),
  }),
  graphql(RUN_UPSERT, {
    props: ({mutate}) => ({
      submit: variables =>
        mutate({
          variables: {...variables},
          updateQueries: {
            Model: (prev, {mutationResult}) => {
              const bucket = mutationResult.data.upsertBucket.bucket;
              return update(prev, {model: {bucket: {$set: bucket}}});
            },
          },
        }),
    }),
  }),
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

//TODO: move parsed loss logic here
function mapStateToProps(state, ownProps) {
  return {
    loss: state.runs[ownProps.match.params.run] || [],
    reduxServerViews: state.views.server,
    reduxBrowserViews: state.views.browser,
  };
}

function mapDispatchToProps(dispatch) {
  return bindActionCreators({updateLocationParams, setServerViews}, dispatch);
}

// export dumb component for testing purposes
export {Run};

export default connect(mapStateToProps, mapDispatchToProps)(
  withMutations(withData(Run)),
);
