import React from 'react';
import {truncateString} from '../util/runhelpers';
import {Popup} from 'semantic-ui-react';
class FixedLengthString extends React.Component {
  constructor(props) {
    super(props);
    this.length = 30;
    this.rightLength = 6;
    this.text = '';
  }

  _setup(props) {
    if (props.length) {
      this.length = props.length;
    }
    if (props.rightLength) {
      this.rightLength = props.rightLength;
    }
    if (props.text) {
      this.text = props.text;
    }
  }

  componentWillMount() {
    this._setup(this.props);
  }

  componentWillReceiveProps(nextProps) {
    this._setup(nextProps);
  }

  render() {
    return this.text && this.text.length > this.length ? (
      <Popup
        on="hover"
        inverted
        size="tiny"
        trigger={
          <span data-tip={this.text}>
            {truncateString(this.text, this.length, this.rightLength)}
          </span>
        }
        content={this.text}
      />
    ) : (
      <span>{this.text}</span>
    );
  }
}

export default FixedLengthString;
