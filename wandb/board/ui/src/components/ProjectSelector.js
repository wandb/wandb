import React, {Component} from 'react';
import {graphql} from 'react-apollo';
import {Dropdown} from 'semantic-ui-react';
import {MODELS_QUERY} from '../graphql/models';

class ProjectsSelector extends Component {
  static defaultProps = {models: {edges: []}};

  render() {
    console.log('proj selector query');
    let options = this.props.models.edges.map(edge => ({
      text: edge.node.name,
      value: edge.node.name,
    }));
    console.log('project selector options', options, this.props.defaultModel);
    return (
      <Dropdown
        fluid
        selection
        options={options}
        value={this.props.value}
        onChange={(e, {value}) => this.props.onChange(value)}
      />
    );
  }
}

const withData = graphql(MODELS_QUERY, {
  options: ({entity}) => ({
    variables: {entityName: entity},
  }),
  props: ({data: {models, error, variables: {entityName}}}) => ({
    models,
    error,
    entity: entityName,
  }),
});

export default withData(ProjectsSelector);
