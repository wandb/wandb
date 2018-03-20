import React from 'react';
import {Label} from 'semantic-ui-react';

export default class Tags extends React.Component {
  render() {
    return this.props.tags.map(tag => (
      <Label style={{padding: '.4em .7em'}} key={tag}>
        {tag}
      </Label>
    ));
  }
}
