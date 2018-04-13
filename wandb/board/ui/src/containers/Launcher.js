import React, {Component} from 'react';
import {Input, Dropdown, Modal, Icon, Header, Button} from 'semantic-ui-react';
import {LAUNCH_RUN} from '../graphql/runs';
import {graphql} from 'react-apollo';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {setFlash} from '../actions';

class Launcher extends Component {
  state = {open: false, image: 'localhost:5000/test', custom: []};
  datasetOptions = ['s3://', 'gs://', 'https://'].map(s => ({
    key: s,
    text: s,
    value: s,
  }));

  show = e => {
    e.preventDefault();
    this.setState({open: true});
  };
  close = () => this.setState({open: false});
  change = (e, {name, value}) => {
    this.setState({[name]: value});
  };
  handleAddition = (e, {value}) => {
    this.setState({
      custom: [{text: value, value}, ...this.state.custom],
    });
  };
  getOptions() {
    //gw000/keras
    return [
      {
        text: 'Keras',
        value: 'localhost:5000/test',
      },
      {
        text: 'Tensorflow',
        value: 'tensorflow/tensorflow',
      },
      {
        text: 'PyTorch',
        value: 'digitalgenius/ubuntu-pytorch',
      },
      {
        text: 'WandB DL',
        value: 'floydhub/dl-docker:cpu',
      },
    ].concat(this.state.custom);
  }

  launch = () => {
    let datasets = [];
    if (this.state.dataset && this.state.dataset.length > 0) {
      datasets = [this.state.dataset];
    }
    this.setState({launching: true});
    this.props
      .launch({
        id: this.props.runId,
        image: this.state.image,
        command: this.state.command,
        datasets,
      })
      .then(result => {
        this.close();
        if (result.data.launchRun.status === 'Failed') {
          this.props.setFlash({
            message: `Pod ${result.data.launchRun.podName} failed to start`,
            color: 'red',
          });
        } else if (result.data.launchRun.status === 'Pending') {
          this.props.setFlash({
            message: `Unable to start ${
              result.data.launchRun.podName
            }, retrying`,
            color: 'orange',
          });
        } else {
          this.props.setFlash({
            message: `Pod ${result.data.launchRun.podName} started`,
            color: 'green',
          });
        }
      });
  };

  render() {
    return (
      <div>
        <Icon
          name="cloud upload"
          className="launcher link blue"
          onClick={this.show}
        />
        <Modal size="small" open={this.state.open} onClose={this.close}>
          <Modal.Header>
            Configure cloud evaluation for run {this.props.runName}
          </Modal.Header>
          <Modal.Content>
            <Header as="h4">Base Image</Header>
            <Dropdown
              selection
              search
              fluid
              name="image"
              value={this.state.image}
              allowAdditions
              additionLabel="Custom image: "
              onAddItem={this.handleAddition}
              options={this.getOptions()}
              onChange={this.change}
            />
            <Header as="h4">Command</Header>
            <Input
              name="command"
              fluid
              label="wandb run"
              labelPosition="left"
              placeholder="Script Name"
              onChange={this.change}
            />
            <Header as="h4">Input Data</Header>
            <Input
              name="dataset"
              fluid
              label={
                <Dropdown defaultValue="s3://" options={this.datasetOptions} />
              }
              labelPosition="left"
              onChange={this.change}
              placeholder="Dataset Url (optional)"
            />
          </Modal.Content>
          <Modal.Actions>
            <Button negative onClick={this.close}>
              Cancel
            </Button>
            <Button
              positive
              icon={
                this.state.launching ? (
                  <Icon loading name="spinner" />
                ) : (
                  'checkmark'
                )
              }
              labelPosition="right"
              content={this.state.launching ? 'Launching' : 'Launch'}
              onClick={this.launch}
            />
          </Modal.Actions>
        </Modal>
      </div>
    );
  }
}

const withMutation = graphql(LAUNCH_RUN, {
  props: ({mutate}) => ({
    launch: vars =>
      mutate({
        variables: vars,
      }),
  }),
});

export default connect(null, (dispatch, ownProps) => {
  return bindActionCreators({setFlash}, dispatch);
})(withMutation(Launcher));
