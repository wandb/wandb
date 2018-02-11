import React, {Component} from 'react';
import {graphql} from 'react-apollo';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {Container, Header, Loader, Item, Button} from 'semantic-ui-react';
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
        <Loader active={this.props.loading} size="massive" />
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
              <ModelHeader condensed={true} model={edge.node} />
              <div style={{marginTop: 16}} />
              <Markdown content={edge.node.description} />
            </Item>
          ))}
          {!this.props.loading &&
            this.models().length === 0 && (
              <Markdown
                content={`
### Install the client and start tracking runs
~~~bash
$ pip install wandb
$ cd training_dir
$ wandb init
$ vi train.py
$ > import wandb
$ > wandb.init()
$ wandb run --show train.py
~~~

<br/>

Visit our [documentation](http://docs.wandb.com/) for more information.
        `}
              />
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

Models = connect(null, modelsMapDispatchToProps)(Models);

// export dumb component for testing purposes
export {Models};

export default withData(Models);
