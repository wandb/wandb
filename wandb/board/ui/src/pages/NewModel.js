import React from 'react';
import {graphql, compose} from 'react-apollo';
import {Container, Header, Loader} from 'semantic-ui-react';
import ModelEditor from '../components/ModelEditor';
import {MODEL_UPSERT} from '../graphql/models';
import {push} from 'react-router-redux';
import {connect} from 'react-redux';

class NewModel extends React.Component {
  constructor(props) {
    super(props);
    this.state = {preview: false, content: '', canSubmit: true};
  }

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  addModel(model) {
    this.props.dispatch(push(`/${model.entityName}/${model.name}`));
  }

  render() {
    return (
      <div className="model">
        <Loader active={this.props.loading} />
        <Header>Create Project</Header>
        <ModelEditor
          entityName={this.props.match.params.entity}
          submit={this.props.submit}
          preview={false}
          viewer={this.props.user}
          loading={this.props.loading}
          addModel={this.addModel.bind(this)}
        />
      </div>
    );
  }
}

const withMutations = compose(
  graphql(MODEL_UPSERT, {
    props: ({ownProps, mutate}) => ({
      submit: ({description, name, entityName, framework}) =>
        mutate({
          variables: {entityName, description, name, framework},
        }),
    }),
  }),
);

// export dumb component for testing purposes
export {NewModel};

export default withMutations(connect()(NewModel));
