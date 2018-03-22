import React from 'react';
import {Label} from 'semantic-ui-react';

export default class Tags extends React.Component {
  render() {
    return this.props.tags.map(tag => (
      <Label
        style={{
          padding: '.4em .7em',
          cursor: this.props.addFilter ? 'pointer' : 'auto',
        }}
        key={tag}
        onClick={() => this.props.addFilter && this.props.addFilter(tag)}>
        {tag}
      </Label>
    ));
  }
}
