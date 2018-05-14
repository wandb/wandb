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
    var {model, condensed, match} = this.props;

    let ModelInfo = (
      <div>
        <ModelHeader {...this.props} />
        <Markdown content={model.description} />
      </div>
    );
    return (
      <div>
        {!condensed && model.bucketCount === 0 ? (
          <div>
            {ModelInfo}
            <br />
            <h4>No runs for this project yet.</h4>
            <p>New to wandb?</p>
            <ol>
              <li>
                Visit the getting started{' '}
                <a href="https://docs.wandb.com/docs/started.html">
                  documentation.
                </a>
              </li>
              <li>
                Take a look at a few{' '}
                <a href="https://docs.wandb.com/docs/examples.html">
                  example projects.
                </a>
              </li>
            </ol>
          </div>
        ) : (
          <Runs
            ModelInfo={ModelInfo}
            model={model}
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
