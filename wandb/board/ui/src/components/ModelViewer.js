import React from 'react';
import Markdown from './Markdown';
import ModelHeader from './ModelHeader';
import Runs from '../containers/Runs';

class ModelViewer extends React.Component {
  static defaultProps = {
    model: {},
  };
  state = {jobId: null};

  onJobSelect = jobId => {
    this.setState({jobId: jobId});
  };

  render() {
    var {project, condensed, match} = this.props;

    let ModelInfo = (
      <div>
        <ModelHeader {...this.props} />
        <Markdown content={project.description} />
      </div>
    );
    return (
      <div>
        {!condensed && project.bucketCount === 0 ? (
          <div>
            {ModelInfo}
            <br />
            <h4>No runs for this project yet.</h4>
            <p>New to wandb?</p>
            <ol>
              <li>
                Visit the getting started{' '}
                <a href="http://docs.wandb.com/#getting-started">
                  documentation.
                </a>
              </li>
              <li>
                Take a look at a few{' '}
                <a href="https://github.com/wandb/examples">
                  example projects.
                </a>
              </li>
            </ol>
          </div>
        ) : (
          <Runs
            ModelInfo={ModelInfo}
            project={project}
            match={match}
            embedded={true}
            jobFilter={this.state.jobId}
            limit={10}
            requestSubscribe={true}
            histQueryKey="runsPage"
            query={{
              entity: match.params.entity,
              model: match.params.model,
              strategy: 'root',
            }}
          />
        )}
      </div>
    );
  }
}

export default ModelViewer;
