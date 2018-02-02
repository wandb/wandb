import React, {Component} from 'react';
import {Button, Header, Icon, Modal} from 'semantic-ui-react';

export default class DangerModel extends Component {
  state = {modalOpen: false};

  handleOpen = e =>
    this.setState({
      modalOpen: true,
    });

  handleClose = e =>
    this.setState({
      modalOpen: false,
    });

  render() {
    return (
      <Modal
        open={this.state.modalOpen}
        trigger={
          <Button
            {...this.props.button}
            onClick={this.handleOpen}
            style={this.props.style}>
            {this.props.text}
          </Button>
        }
        basic
        size="small">
        <Header icon={this.props.icon || 'cancel'} content="Danger" />
        <Modal.Content>
          <p>{this.props.message || 'Are you absolutely sure?'}</p>
        </Modal.Content>
        <Modal.Actions>
          <Button basic color="red" inverted onClick={this.handleClose}>
            <Icon name="remove" /> No
          </Button>
          <Button
            color="green"
            inverted
            onClick={() => {
              if (this.props.yes) {
                this.props.yes();
              }
              this.handleClose();
            }}>
            <Icon name="checkmark" /> Yes
          </Button>
        </Modal.Actions>
      </Modal>
    );
  }
}
