import React, {Component} from 'react';
import {
  Button,
  Grid,
  Header,
  Modal,
  Message,
  Segment,
} from 'semantic-ui-react';
import {NavLink} from 'react-router-dom';
import Markdown from './Markdown';
import TimeAgo from 'react-timeago';

class RunSummary extends Component {
  color() {
    switch (this.props.bucket.state) {
      case 'running':
        return 'blue';
      case 'finished':
        return 'green';
      case 'killed':
        return 'orange';
      case 'crashed':
      case 'failed':
        return 'red';
      default:
        return 'blue';
    }
  }

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  render() {
    const {model, bucket} = this.props;
    const parts = (bucket.description || 'No run message').trim().split('\n'),
      header = parts.shift(),
      body = parts.join('\n');
    return (
      <div>
        <Message
          attached
          header={
            <div>
              <Header style={{display: 'inline'}}>
                {header.substring(0, 70)}
              </Header>
              <Button.Group
                style={{position: 'relative', top: -3}}
                size="tiny"
                floated="right">
                <NavLink
                  to={`/${model.entityName}/${model.name}/runs/${
                    bucket.name
                  }/edit`}>
                  <Button icon="edit" basic />
                </NavLink>
                {bucket.sweep &&
                  bucket.state === 'running' && (
                    <Button
                      icon="stop circle"
                      onClick={() => {
                        if (window.confirm('Should we stop this run?')) {
                          this.props.onStop(bucket.id);
                        }
                      }}
                      negative
                    />
                  )}
              </Button.Group>
            </div>
          }
          content={body.length > 0 && <Markdown content={body} />}
          color={this.color()}
        />
        <Segment attached="bottom">
          <Grid>
            <Grid.Row>
              <Grid.Column width={10}>
                <strong>
                  ran {bucket.user && 'by ' + bucket.user.username}{' '}
                  {bucket.heartbeatAt && (
                    <span>
                      for{' '}
                      <TimeAgo
                        date={bucket.createdAt + 'Z'}
                        now={() => {
                          return Date.parse(bucket.heartbeatAt + 'Z');
                        }}
                        formatter={(v, u, s, d, f) => f().replace(s, '')}
                        live={false}
                      />
                    </span>
                  )}
                </strong>
                {bucket.host && ' on ' + bucket.host}
              </Grid.Column>
              <Grid.Column width={6} textAlign="right">
                run{' '}
                <NavLink
                  to={`/${model.entityName}/${model.name}/runs/${bucket.name}`}>
                  {bucket.name}
                </NavLink>
                {bucket.commit && (
                  <Modal
                    on="click"
                    trigger={
                      <span className="commit">
                        &nbsp;&nbsp;&nbsp;&nbsp; commit{' '}
                        <a
                          onClick={e => e.preventDefault()}
                          href={bucket.github}>
                          {bucket.commit}
                        </a>
                      </span>
                    }>
                    <Modal.Header>
                      <h1>Git commit</h1>
                    </Modal.Header>
                    <Modal.Content>
                      <p>
                        Wandb saves the commit ID of the last commit before
                        every run.
                      </p>

                      <p>
                        If you pushed the commit to github, you can find your
                        commit at <a href={bucket.github}>this github link</a>.
                      </p>

                      <p>
                        If you made changes before running and did not commit
                        them, wandb saves the changes in a patch (.diff) file.
                      </p>
                    </Modal.Content>
                  </Modal>
                )}
              </Grid.Column>
            </Grid.Row>
          </Grid>
        </Segment>
      </div>
    );
  }
}

export default RunSummary;
