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

    return (
      <div>
        <ModelHeader {...this.props} />
        <Markdown content={model.description} />
        {!condensed &&
          model.bucketCount === 0 && (
            <div>
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

          )}
        {/*!condensed && (
          <div style={{marginTop: 30, width: '100%'}}>
            <Jobs model={model} match={match} onSelect={this.onJobSelect} />
          </div>
        )*/}
        {!condensed &&
          model.bucket.name !== 'tmp' && (
            <div style={{marginTop: 30, width: '100%'}}>
              <Runs
                model={model}
                match={match}
                embedded={true}
                jobFilter={this.state.jobId}
                limit={10}
                histQueryKey="runsPage"
                query={{
                  entity: match.params.entity,
                  model: match.params.model,
                  strategy: 'merge',
                }}
              />
            </div>
          )}
      </div>
    );
  }
}

export default ModelViewer;
