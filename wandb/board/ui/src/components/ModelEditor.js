import React from 'react';
import {Button, Form} from 'semantic-ui-react';
import DangerModal from './DangerModal';
import Markdown from './Markdown';
import Breadcrumbs from './Breadcrumbs';

class ModelEditor extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      preview: false,
      name: props.model.name || '',
      framework: props.model.framework || props.viewer.defaultFramework,
      access: props.model.access || 'ENTITY_WRITE',
      content: props.model.description || '',
      canSubmit: false,
    };
  }

  static defaultProps = {
    model: {},
  };

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  componentWillReceiveProps(props) {
    if (!this.state.canSubmit) {
      this.setState({
        preview: props.preview,
        framework: props.model.framework,
        name: props.model.name || '',
        content: props.model.description,
      });
    }
  }

  admin() {
    return this.props.viewer.admin;
  }

  slugFormat(e) {
    this.setState({
      canSubmit: true,
      name: e.target.value
        .toLowerCase()
        .replace(/\W+/g, '-')
        .replace(/(-)\1/g, '-'),
    });
  }

  permToEnglish(perm) {
    switch (perm) {
      case 'USER_WRITE':
        return 'World writable';
      case 'USER_READ':
        return 'World readable';
      case 'ENTITY_WRITE':
        return 'Team writable';
      case 'ENTITY_READ':
        return 'Team readable';
      case 'PRIVATE':
        return 'Private';
      default:
        return;
    }
  }

  render() {
    return (
      <Form className="ui form">
        <Breadcrumbs
          entity={this.props.model.entityName}
          model={this.props.model.name}
        />
        <Form.Field className="model_name">
          <label>Name</label>
          <Form.Input
            name="id"
            transparent={this.state.preview}
            size="huge"
            placeholder="Project name"
            value={this.state.name}
            onChange={this.slugFormat.bind(this)}
          />
        </Form.Field>
        <Form.Field>
          <label>Description</label>
          {this.state.preview ? (
            <Markdown content={this.state.content} />
          ) : (
            <Form.TextArea
              name="description"
              rows={12}
              onChange={e =>
                this.setState({
                  canSubmit: true,
                  content: e.target.value,
                })}
              placeholder="Provide a description about this project"
              value={this.state.content}
            />
          )}
        </Form.Field>
        {!this.state.preview && (
          <Form.Select
            inline
            label="Access"
            placeholder="Permissions"
            value={this.state.access}
            options={[
              'USER_WRITE',
              'USER_READ',
              'ENTITY_WRITE',
              'ENTITY_READ',
              'PRIVATE',
            ].map(e => {
              return {
                text: this.permToEnglish(e),
                value: e,
              };
            })}
            onChange={(e, d) =>
              this.setState({
                access: d.value,
                canSubmit: d.value !== this.state.framework,
              })}
          />
        )}
        <Button.Group>
          <Button onClick={() => this.setState({preview: !this.state.preview})}>
            {this.state.preview ? 'Edit' : 'Preview'}
          </Button>
          <Button.Or />
          <Button
            disabled={!this.state.canSubmit}
            content={this.props.model.id ? 'Update' : 'Create'}
            color="blue"
            onClick={e => {
              e.preventDefault();
              this.setState({canSubmit: false});
              this.props
                .submit({
                  description: this.state.content,
                  framework: this.state.framework,
                  access: this.state.access,
                  id: this.props.model.id,
                  name: this.state.name,
                  entityName:
                    this.props.entityName || this.props.model.entityName,
                })
                .then(res => {
                  if (res.data.upsertModel.inserted) {
                    this.setState({
                      canSubmit: true,
                      content: '',
                      name: '',
                    });
                    if (this.props.addModel)
                      this.props.addModel(res.data.upsertModel.model);
                  } else {
                    window.location.href = `/${this.props.model
                      .entityName}/${res.data.upsertModel.model.name}`;
                  }
                });
            }}
          />
        </Button.Group>

        <Button.Group size="small" floated="right">
          {this.admin() &&
          this.props.model.id && (
            <DangerModal
              button={{negative: true, icon: 'trash'}}
              yes={() => this.props.delete(this.props.model.id)}
            />
          )}
        </Button.Group>
      </Form>
    );
  }
}

export default ModelEditor;
