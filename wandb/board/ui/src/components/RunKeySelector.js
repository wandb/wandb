import React from 'react';
import {Dropdown} from 'semantic-ui-react';
import * as UI from '../util/uihelpers';
import * as Run from '../util/runhelpers';
import _ from 'lodash';

export default class RunKeySelector extends React.Component {
  state = {value: ''};

  searchFunction = (options, query) => {
    let matched = Run.fuzzyMatch(options.map(option => option.text), query);
    return matched.map(v => ({
      content: Run.fuzzyMatchHighlight(v, query),
      key: v,
      value: v,
    }));
  };

  componentWillMount() {
    this.setState({value: this.props.storedKey});
  }

  componentWillReceiveProps(nextProps) {
    if (nextProps.storedKey !== this.props.storedKey) {
      this.setState({value: nextProps.storedKey});
    }
  }

  render() {
    let {keys} = this.props;
    console.log('stored', this.props.storedKey);
    if (this.props.storedKey && _.indexOf(keys, this.props.storedKey) < 0) {
      keys.push(this.props.storedKey);
    }
    return (
      <Dropdown
        options={UI.makeOptions(keys)}
        placeholder="Key"
        search={this.searchFunction}
        selection
        fluid
        value={this.state.value}
        onChange={(e, {value}) => {
          console.log('have value', value);
          if (_.indexOf(this.props.keys, value) >= 0) {
            console.log('valid selection');
            this.props.onValidSelection(value);
          }
          this.setState({value: value});
        }}
      />
    );
  }
}
