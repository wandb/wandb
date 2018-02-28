import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {Form} from 'semantic-ui-react';
import update from 'immutability-helper';
import * as Query from '../util/query';
import RunFilters from '../components/RunFilters';

class QueryEditor extends React.Component {
  setStrategy(strategy) {
    this.props.setQuery(update(this.query, {strategy: {$set: strategy}}));
  }

  setFilters(newFilters) {
    this.props.setQuery(
      update(this.query, {
        filters: {
          $set: newFilters,
        },
      }),
    );
  }

  addFilter(key, op, value) {
    this.setFilters(Query.addFilter(this.filters, key, op, value));
  }

  deleteFilter(id) {
    this.setFilters(Query.deleteFilter(this.filters, id));
  }

  setFilterComponent(id, component, value) {
    this.setFilters(
      Query.setFilterComponent(this.filters, id, component, value),
    );
  }

  render() {
    let {setQuery, runs, keySuggestions} = this.props;
    this.query = this.props.query || {};
    let strategy = this.query.strategy;
    if (strategy !== 'page' && strategy !== 'merge') {
      strategy = 'page';
    }
    this.filters = this.query.filters || {};

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
          {strategy === 'merge' && (
            <RunFilters
              filters={this.filters}
              runs={runs}
              keySuggestions={keySuggestions}
              addFilter={(_, key, op, value) => this.addFilter(key, op, value)}
              deleteFilter={(_, id) => this.deleteFilter(id)}
              setFilterComponent={(_, id, component, value) =>
                this.setFilterComponent(id, component, value)
              }
              buttonText="Add Filter"
            />
          )}
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
