import React, {Component} from 'react';
import {graphql} from 'react-apollo';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {Container, Header, Item, Button} from 'semantic-ui-react';
import Loader from '../components/Loader';
import ModelHeader from '../components/ModelHeader';
import Markdown from '../components/Markdown';
import ErrorPage from '../components/ErrorPage';
import {MODELS_QUERY} from '../graphql/models';
import {updateLocationParams} from '../actions/location';

class Models extends Component {
  componentWillMount() {
    this.props.updateLocationParams({
      entity: this.props.match.params.entity,
      model: null,
    });
  }

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  models() {
    return (this.props.models && this.props.models.edges) || [];
  }

  render() {
    return this.props.error ? (
      <ErrorPage error={this.props.error} history={this.props.history} />
    ) : (
      <Container>
        <Loader />
        {this.props.user && (
          <Button
            as="a"
            href={`/${this.props.entity}/new`}
            style={{zIndex: 5}}
            floated="right">
            Create Project
          </Button>
        )}
        <Header style={{marginRight: 200}}>Projects</Header>
        <Item.Group divided relaxed>
          {this.models().map(edge => (
            <Item style={{display: 'block'}} key={edge.node.id}>
              <ModelHeader condensed={true} project={edge.node} />
              <div style={{marginTop: 16}} />
              <Markdown content={edge.node.description} />
            </Item>
          ))}
          {!this.props.loading &&
            this.models().length === 0 && (
              <div>
                <br />
                <h4>No runs for this project yet.</h4>
                <p>New to wandb?</p>
                <ol>
                  <li>
                    Visit the getting started{' '}
                    <a href="http://docs.wandb.com/#getting-started">
                      documentation.
                    </a>
                  </li>
                  <li>
                    Take a look at our{' '}
                    <a href="https://github.com/wandb/examples">
                      example projects.
                    </a>
                  </li>
                </ol>
              </div>
            )}
        </Item.Group>
      </Container>
    );
  }
}

Models.defaultProps = {
  models: {edges: []},
};

const withData = graphql(MODELS_QUERY, {
  options: ({match: {params}}) => ({
    variables: {entityName: params.entity || 'models'},
  }),
  props: ({
    data: {loading, models, fetchMore, error, variables: {entityName}},
  }) => ({
    loading,
    models,
    error,
    entity: entityName,
    loadMoreEntries: () => {
      return fetchMore({
        query: MODELS_QUERY,
        variables: {
          cursor: models.pageInfo.endCursor,
        },
        updateQuery: (previousResult, {fetchMoreResult}) => {
          const newEdges = fetchMoreResult.data.models.edges;
          const pageInfo = fetchMoreResult.data.models.pageInfo;
          return {
            comments: {
              edges: [...previousResult.models.edges, ...newEdges],
              pageInfo,
            },
          };
        },
      });
    },
  }),
});

const modelsMapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({updateLocationParams}, dispatch);
};

// export dumb component for testing purposes
export {Models};

export default withData(connect(null, modelsMapDispatchToProps)(Models));
