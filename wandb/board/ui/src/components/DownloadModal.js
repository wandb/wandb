import React, {Component} from 'react';
import {Modal, Button, List} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import numeral from 'numeral';

export default class DownloadModal extends Component {
  state = {modalOpen: false, loading: false};

  handleOpen = e =>
    this.setState({
      modalOpen: true,
    });

  handleClose = e =>
    this.setState({
      modalOpen: false,
    });

  weightsFile() {
    return this.props.files.edges[0].node;
  }

  modelFile() {
    return (this.props.files.edges[1] || {}).node;
  }

  render() {
    return (
      <Modal
        trigger={<Button icon="download" onClick={this.handleOpen} />}
        open={this.state.modalOpen}
        onClose={this.handleClose}>
        <Modal.Header>Download your files</Modal.Header>
        <Modal.Content>
          <Modal.Description>
            <List divided relaxed>
              {this.props.files.edges.map((file, i) => (
                <List.Item key={i}>
                  <List.Icon
                    loading={this.state.loading === i}
                    name="copy"
                    size="large"
                    verticalAlign="middle"
                  />
                  <List.Content>
                    <List.Header
                      as="a"
                      href={file.node.url}
                      onClick={e => {
                        if (file.node.name.match(/\.log$/)) {
                          e.preventDefault();
                          this.setState({loading: i});
                          fetch(file.node.url + '?redirect=false').then(res =>
                            res.json().then(body =>
                              fetch(body.url).then(res =>
                                res.text().then(text =>
                                  this.setState({
                                    logModal: text,
                                    loading: false,
                                    url: file.node.url,
                                  }),
                                ),
                              ),
                            ),
                          );
                        }
                      }}>
                      {file.node.name}
                    </List.Header>
                    <List.Description>
                      Updated <TimeAgo date={file.node.updatedAt + 'Z'} />
                      , {numeral(file.node.sizeBytes).format('0.0b')}
                    </List.Description>
                  </List.Content>
                </List.Item>
              ))}
            </List>
            <Button
              floated="right"
              onClick={() => {
                this.handleClose();
              }}>
              Close
            </Button>
            <pre className="instructions">
              <code className="language-shell">
                wandb pull {this.props.model.name}/{this.props.name}
              </code>
            </pre>
          </Modal.Description>
        </Modal.Content>
      </Modal>
    );
  }
}
