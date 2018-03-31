import React, {Component} from 'react';
import {
  Button,
  Label,
  Grid,
  Header,
  Modal,
  Message,
  Segment,
} from 'semantic-ui-react';
import {NavLink} from 'react-router-dom';
import Markdown from './Markdown';
import Tags from './Tags';
import TimeAgo from 'react-timeago';

/**
 *  This component makes the summary on top of a runs page.
 */

class RunSummary extends Component {
  color() {
    switch (this.props.run.state) {
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
    const {project, run} = this.props;
    const parts = (run.description || 'No run message').trim().split('\n'),
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
                  to={`/${project.entityName}/${project.name}/runs/${
                    run.name
                  }/edit`}>
                  <Button icon="edit" basic />
                </NavLink>
                {run.sweep &&
                  run.state === 'running' && (
                    <Button
                      icon="stop circle"
                      onClick={() => {
                        if (window.confirm('Should we stop this run?')) {
                          this.props.onStop(run.id);
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
              <Grid.Column width={8}>
                {this.props.run.state == 'running' ? (
                  <strong>running </strong>
                ) : (
                  <strong>ran </strong>
                )}
                {run.user && this.props.run.state == 'running' ? (
                  <span>for </span>
                ) : (
                  <span>by </span>
                )}
                {run.user && <strong>{run.user.username}</strong>}{' '}
                {run.heartbeatAt && (
                  <span>
                    for{' '}
                    <strong>
                      <TimeAgo
                        date={run.createdAt + 'Z'}
                        now={() => {
                          return Date.parse(run.heartbeatAt + 'Z');
                        }}
                        formatter={(v, u, s, d, f) => f().replace(s, '')}
                        live={false}
                      />
                    </strong>
                  </span>
                )}
                {run.host && (
                  <span>
                    on <strong>{run.host}</strong>
                  </span>
                )}
              </Grid.Column>
              <Grid.Column width={8} textAlign="right">
                {run.tags &&
                  run.tags.length > 0 && (
                    <span>
                      tags <Tags tags={run.tags} />{' '}
                    </span>
                  )}
                run{' '}
                <NavLink
                  to={`/${project.entityName}/${project.name}/runs/${
                    run.name
                  }`}>
                  {run.name}
                </NavLink>
                {run.commit && ' commit '}
                {run.commit && (
                  <Modal
                    on="click"
                    trigger={
                      <a onClick={e => e.preventDefault()} href={run.github}>
                        {run.commit.slice(0, 6)}
                      </a>
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
                        commit at <a href={run.github}>this github link</a>.
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
