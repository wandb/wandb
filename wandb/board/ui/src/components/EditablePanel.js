import React from 'react';
import _ from 'lodash';
import {
  Button,
  Card,
  Dropdown,
  Grid,
  Icon,
  Segment,
  Modal,
} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';
import {sortRuns} from '../util/runhelpers.js';
import withRunsDataLoader from '../containers/RunsDataLoader';
import ContentLoader from 'react-content-loader';
import Panel from '../components/Panel';

class EditablePanel extends React.Component {
  state = {editing: false};

  componenWillMount() {
    this.externalOpened = false;
  }

  componentWillReceiveProps(nextProps) {
    if (!this.externalOpened && nextProps.openEdit) {
      this.setState({editing: true});
      this.externalOpened = true;
    }
  }

  render() {
    return (
      <div
        onMouseDown={e => {
          if (!this.props.editMode) {
            // Stop propagation to prevent react-grid-layout from receiving it.
            // This stops the panel from being draggable / resizeable when not
            // in edit mode.
            e.stopPropagation();
          }
        }}>
        <Modal
          open={this.state.editing}
          dimmer="blurring"
          trigger={
            <Icon
              style={{backgroundColor: 'white'}}
              link
              name="edit"
              size="large"
              onClick={() => this.setState({editing: true})}
            />
          }>
          <Modal.Header>Edit Panel</Modal.Header>
          <Modal.Content style={{padding: 16}}>
            <Panel {...this.props} editMode={true} />
          </Modal.Content>
          <Modal.Actions>
            <Button
              floated="left"
              onClick={() => {
                this.props.removePanel();
                this.setState({editing: false});
              }}>
              <Icon name="trash" />Delete Chart
            </Button>
            <Button primary onClick={() => this.setState({editing: false})}>
              OK
            </Button>
          </Modal.Actions>
        </Modal>
        <Modal
          open={this.state.zooming}
          dimmer="blurring"
          size="fullscreen"
          trigger={
            <Icon
              link
              name="zoom"
              onClick={() => this.setState({zooming: true})}
            />
          }>
          <Modal.Content style={{padding: 16, height: '500'}}>
            <Panel {...this.props} editMode={false} currentHeight={500} />
          </Modal.Content>
          <Modal.Actions>
            <Button primary onClick={() => this.setState({zooming: false})}>
              OK
            </Button>
          </Modal.Actions>
        </Modal>
        <Panel {...this.props} editMode={false} />
      </div>
    );
  }
}

export default withRunsDataLoader(EditablePanel);
