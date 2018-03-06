import React from 'react';
import {Button, Form} from 'semantic-ui-react';
import Markdown from './Markdown';
import Breadcrumbs from './Breadcrumbs';
import _ from 'lodash';
import {Label, Icon} from 'semantic-ui-react';

// TODO: we might want to merge with ModelEditor
class RunEditor extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      newTag: '',
      tags: [],
      preview: false,
      name: props.bucket.name || '',
      content: props.bucket.description || '',
      canSubmit: false,
    };
  }

  static defaultProps = {
    model: {},
  };

  componentWillReceiveProps(props) {
    if (!this.state.canSubmit) {
      this.setState({
        tags: _.sortedUniq(props.bucket.tags),
        preview: props.preview,
        name: props.bucket.name || '',
        content: props.bucket.description,
      });
    }
  }

  render() {
    return (
      <Form className="ui form">
        <Breadcrumbs
          entity={this.props.model.entityName}
          model={this.props.model.name}
          run={this.props.bucket.name}
        />
        <Form.Field>
          <label>Description</label>
          {this.state.preview ? (
            <Markdown content={this.state.content} />
          ) : (
            <Form.TextArea
              name="description"
              rows={12}
              onChange={e =>
                this.setState({canSubmit: true, content: e.target.value})
              }
              placeholder="Provide a description about this project"
              value={this.state.content}
            />
          )}
        </Form.Field>
        <Form.Group label="Tags">
          <Form.Input
            width={3}
            value={this.state.newTag}
            onChange={e => {
              this.setState({newTag: e.target.value});
            }}
          />
          <Button
            onClick={e => {
              e.preventDefault();
              if (this.state.newTag.length) {
                this.setState({
                  canSubmit: true,
                  tags: _.sortedUniq(
                    _.concat(this.state.tags, this.state.newTag),
                  ),
                  newTag: '',
                });
              }
            }}>
            Add
          </Button>
        </Form.Group>
        <Form.Group>
          {this.state.tags.map(tag => (
            <Label key={tag}>
              {tag}
              <Icon
                name="delete"
                onClick={e => {
                  e.preventDefault();
                  this.setState({
                    canSubmit: true,
                    tags: this.state.tags.filter(t => t !== tag),
                  });
                }}
              />
            </Label>
          ))}
        </Form.Group>
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
                  tags: this.state.tags,
                  description: this.state.content,
                  id: this.props.bucket.id,
                })
                .then(res => {
                  window.location.href = `/${this.props.model.entityName}/${
                    this.props.model.name
                  }/runs/${res.data.upsertBucket.bucket.name}`;
                });
            }}
          />
        </Button.Group>
      </Form>
    );
  }
}

export default RunEditor;
