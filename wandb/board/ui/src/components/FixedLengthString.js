import React from 'react';
import ReactTooltip from 'react-tooltip';
import {truncateString} from '../util/runhelpers';

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
      <span data-tip={this.text}>
        {truncateString(this.text, this.length, this.rightLength)}
        <ReactTooltip />
      </span>
    ) : (
      <span>{this.text}</span>
    );
  }
}

export default FixedLengthString;
