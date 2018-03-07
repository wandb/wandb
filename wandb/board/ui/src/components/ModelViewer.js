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
            <Markdown
              content={`
### Sync runs to this project with the wandb module:
~~~bash
$ pip install wandb
$ cd training_dir
$ wandb init
$ vi train.py
$ > import wandb
$ > wandb.init()
$ wandb run train.py
~~~

<br/>

Visit our [documentation](http://docs.wandb.com/) for more information.
        `}
            />
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
