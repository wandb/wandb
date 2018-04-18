import * as _ from 'lodash';
import * as React from 'react';
import {Dropdown} from 'semantic-ui-react';
import * as RunHelpers from '../util/runhelpers';
import * as UI from '../util/uihelpers';

interface RunKeySelectorProps {
  storedKey: string;
  keys: string[];
  disabled: boolean;
  onValidSelection(key: string): void;
}
export default class RunKeySelector extends React.Component<
  RunKeySelectorProps,
  {}
> {
  dropdownEl: any = null;
  state = {value: ''};

  searchFunction = (options: any, query: any) => {
    const matched = RunHelpers.fuzzyMatch(
      options.map((option: any) => option.text),
      query
    );
    return matched.map((v: any) => ({
      content: RunHelpers.fuzzyMatchHighlight(v, query),
      key: v,
      value: v,
    }));
  };

  componentWillMount() {
    this.setState({value: this.props.storedKey});
  }

  componentWillReceiveProps(nextProps: RunKeySelectorProps) {
    if (nextProps.storedKey !== this.props.storedKey) {
      this.setState({value: nextProps.storedKey});
    }
  }

  render() {
    const {keys} = this.props;
    if (
      this.props.storedKey &&
      this.props.storedKey !== '-' &&
      _.indexOf(keys, this.props.storedKey) < 0
    ) {
      keys.unshift(this.props.storedKey);
    }
    return (
      <Dropdown
        disabled={this.props.disabled}
        ref={el => (this.dropdownEl = el)}
        options={UI.makeOptions(keys)}
        placeholder="Key"
        search={this.searchFunction}
        selection
        fluid
        value={this.state.value}
        onChange={(e, {value}) => {
          if (
            _.indexOf(this.props.keys, value) >= 0 &&
            typeof value === 'string'
          ) {
            this.props.onValidSelection(value);
          }
          this.setState({value});
        }}
      />
    );
  }
}
