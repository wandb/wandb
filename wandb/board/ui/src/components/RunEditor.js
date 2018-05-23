import React from 'react';
import {Button, Form} from 'semantic-ui-react';
import Markdown from './Markdown';
import Breadcrumbs from './Breadcrumbs';
import _ from 'lodash';
import {Label, Icon, Grid} from 'semantic-ui-react';
// TODO: we might want to merge with ModelEditor
class RunEditor extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      newTag: '',
      tags: [],
      preview: false,
      name: props.run.name || '',
      content: props.run.description || '',
      canSubmit: false,
    };
  }

  static defaultProps = {
    project: {},
  };

  componentWillReceiveProps(props) {
    if (!this.state.canSubmit) {
      let description = props.run.description;
      if (description == props.run.name) {
        description = '';
      }
      this.setState({
        tags: _.sortedUniq(props.run.tags),
        preview: props.preview,
        name: props.run.name || '',
        content: description,
      });
    }
  }

  render() {
    return (
      <Form className="ui form">
        <Grid>
          {!this.props.jupyter && (
            <Grid.Row>
              <Grid.Column>
                <Breadcrumbs
                  entity={this.props.project.entityName}
                  model={this.props.project.name}
                  run={this.props.run.name}
                />
              </Grid.Column>
            </Grid.Row>
          )}
          <Grid.Row>
            <Grid.Column>
              <Form.Field>
                <label>Description</label>
                {this.state.preview ? (
                  <div style={{minHeight: 120}}>
                    <Markdown content={this.state.content} />
                  </div>
                ) : (
                  <Form.TextArea
                    name="description"
                    rows={6}
                    onChange={e =>
                      this.setState({canSubmit: true, content: e.target.value})
                    }
                    placeholder="Provide a description of this experiment"
                    value={this.state.content}
                  />
                )}
              </Form.Field>
            </Grid.Column>
          </Grid.Row>
          <Grid.Row>
            <Grid.Column width={4}>
              <Button.Group>
                <Button
                  onClick={() => this.setState({preview: !this.state.preview})}>
                  {this.state.preview ? 'Edit' : 'Preview'}
                </Button>
                <Button.Or />
                <Button
                  disabled={!this.state.canSubmit}
                  content={this.props.project.id ? 'Update' : 'Create'}
                  color="blue"
                  onClick={e => {
                    e.preventDefault();
                    this.setState({canSubmit: false});
                    this.props
                      .submit({
                        tags: this.state.tags,
                        description: this.state.content,
                        id: this.props.run.id,
                      })
                      .then(res => {
                        if (this.props.jupyter) {
                          this.setState({preview: true});
                        } else {
                          this.props.history.push(
                            `/${this.props.project.entityName}/${
                              this.props.project.name
                            }/runs/${res.data.upsertBucket.bucket.name}`
                          );
                        }
                      });
                  }}
                />
              </Button.Group>
            </Grid.Column>
            {!this.state.preview && (
              <Grid.Column width={6}>
                <Form.Group>
                  <Form.Field>
                    <label>Tags</label>
                  </Form.Field>
                  <Form.Input
                    width={13}
                    value={this.state.newTag}
                    onChange={(e, {value}) => {
                      this.setState({newTag: value});
                    }}
                  />
                  <Button
                    icon="plus"
                    content="Add"
                    className="labeled"
                    onClick={e => {
                      e.preventDefault();
                      if (this.state.newTag.length) {
                        this.setState({
                          canSubmit: true,
                          tags: _.sortedUniq(
                            _.concat(this.state.tags, this.state.newTag)
                          ),
                          newTag: '',
                        });
                      }
                    }}
                  />
                </Form.Group>
              </Grid.Column>
            )}
            <Grid.Column width={6}>
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
            </Grid.Column>
          </Grid.Row>
        </Grid>
      </Form>
    );
  }
}

export default RunEditor;
