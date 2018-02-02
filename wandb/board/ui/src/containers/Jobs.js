import React from 'react';
import {graphql, withApollo} from 'react-apollo';
import {Container, Header, Button, Grid} from 'semantic-ui-react';
import JobFeed from '../components/JobFeed';
import {JOBS_QUERY} from '../graphql/jobs';
import {NavLink} from 'react-router-dom';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {updateJob} from '../actions/run';

class Jobs extends React.Component {
  render() {
    return (
      <Container>
        <Grid>
          <Grid.Column width={6}>
            <Header as="h3">Jobs</Header>
          </Grid.Column>
        </Grid>
        <JobFeed
          jobs={this.props.jobs}
          project={this.props.model}
          onSelect={id => this.props.updateJob(id)}
        />
      </Container>
    );
  }
}

const withData = graphql(JOBS_QUERY, {
  options: ({match: {params, path}, user, embedded}) => {
    return {
      variables: {
        entityName: params.entity,
        name: params.model,
      },
    };
  },
  props: ({data: {loading, model, viewer, refetch}, errors}) => ({
    loading,
    refetch,
    jobs: model && model.jobs,
    viewer,
  }),
});

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({updateJob}, dispatch);
};

export default connect(null, mapDispatchToProps)(withApollo(withData(Jobs)));
