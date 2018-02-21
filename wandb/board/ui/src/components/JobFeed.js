import React, {Component} from 'react';
import {Table} from 'semantic-ui-react';
import {connect} from 'react-redux';

class JobFeed extends Component {
  onSelect = id => {
    this.props.onSelect(id);
  };
  render() {
    return (
      <div style={{marginTop: 10}}>
        {(this.props.jobs &&
        this.props.jobs.edges.length && (
          <Table celled selectable striped compact unstackable size="small">
            <Table.Header>
              <Table.Row>
                <Table.HeaderCell>Type</Table.HeaderCell>
                <Table.HeaderCell>Repo</Table.HeaderCell>
                <Table.HeaderCell>Image</Table.HeaderCell>
                <Table.HeaderCell>Program</Table.HeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {this.props.jobs.edges.map((edge, i) => {
                let job = edge.node;
                return (
                  <Table.Row
                    active={this.props.jobId === edge.node.id}
                    key={edge.node.id}
                    onClick={() =>
                      this.onSelect(
                        this.props.jobId !== edge.node.id ? edge.node.id : null,
                      )}>
                    <Table.Cell>{job.type}</Table.Cell>
                    <Table.Cell>{job.repo}</Table.Cell>
                    <Table.Cell>{job.dockerImage}</Table.Cell>
                    <Table.Cell>{job.program}</Table.Cell>
                  </Table.Row>
                );
              })}
            </Table.Body>
          </Table>
        )) || (
          <p>
            No jobs have been created for this project. Launch a new run to
            automatically create one.
          </p>
        )}
      </div>
    );
  }
}
function mapStateToProps(state, ownProps) {
  return {
    jobId: state.runs.currentJob,
  };
}
export default connect(mapStateToProps)(JobFeed);
