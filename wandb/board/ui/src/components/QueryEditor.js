import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {Form} from 'semantic-ui-react';
import update from 'immutability-helper';

class QueryEditor extends React.Component {
  setStrategy(strategy) {
    this.props.setQuery(update(this.query, {strategy: {$set: strategy}}));
  }

  render() {
    let {setQuery} = this.props;
    this.query = this.props.query || {};
    let strategy = this.query.strategy;
    if (strategy !== 'page' && strategy !== 'merge') {
      strategy = 'page';
    }

    return (
      <Form>
        <Form.Group inline>
          <Form.Radio
            label="Use Page Query"
            checked={strategy === 'page'}
            onChange={() => this.setStrategy('page')}
          />
          <Form.Radio
            label="Merge with Page Query"
            checked={strategy === 'merge'}
            onChange={() => this.setStrategy('merge')}
          />
        </Form.Group>
      </Form>
    );
  }
}

const S2P = (state, ownProps) => {
  return {};
};

const D2P = (dispatch, ownProps) => {
  return bindActionCreators({}, dispatch);
};

export default connect(S2P, D2P)(QueryEditor);
