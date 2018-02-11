import React, {Component} from 'react';
import {List} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import numeral from 'numeral';

class Files extends Component {
  render() {
    return (
      <List divided relaxed inverted>
        {this.props.files.edges.map((file, i) => (
          <List.Item key={i}>
            <List.Icon name="copy" size="large" verticalAlign="middle" />
            <List.Content>
              <List.Header as="a" href={file.node.url} onClick={e => {}}>
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
    );
  }
}

export default Files;
