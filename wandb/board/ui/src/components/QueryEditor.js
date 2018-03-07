import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {Form, Checkbox} from 'semantic-ui-react';
import update from 'immutability-helper';
import * as Query from '../util/query';
import RunFilters from '../components/RunFilters';
import ProjectSelector from '../components/ProjectSelector';

class QueryEditor extends React.Component {
  setStrategy(strategy) {
    this.props.setQuery(update(this.query, {strategy: {$set: strategy}}));
  }

  setProject(project) {
    this.props.setQuery(update(this.query, {model: {$set: project}}));
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
    this.query = this.props.panelQuery || {};
    let strategy = this.query.strategy;
    if (strategy !== 'page' && strategy !== 'merge') {
      strategy = 'page';
    }
    this.filters = this.query.filters || {};
    let project = this.query.model || '';

    return (
      <Form style={{marginBottom: 20}}>
        <Form.Field style={{marginBottom: 8}}>
          <Checkbox
            label="Custom Query"
            checked={strategy === 'merge'}
            onChange={() =>
              strategy === 'page'
                ? this.setStrategy('merge')
                : this.setStrategy('page')
            }
          />
        </Form.Field>
        {strategy === 'merge' && (
          <Form.Group style={{marginLeft: 20}}>
            <Form.Field width={4}>
              <label>Project</label>
              <ProjectSelector
                entity={this.props.pageQuery.entity}
                value={this.query.model || this.props.pageQuery.model}
                onChange={project => this.setProject(project)}
              />
            </Form.Field>
            <Form.Field width={10}>
              <label>Filters</label>
              <RunFilters
                filters={this.filters}
                runs={runs}
                keySuggestions={keySuggestions}
                addFilter={(_, key, op, value) =>
                  this.addFilter(key, op, value)
                }
                deleteFilter={(_, id) => this.deleteFilter(id)}
                setFilterComponent={(_, id, component, value) =>
                  this.setFilterComponent(id, component, value)
                }
                buttonText="Add Filter"
                nobox
              />
            </Form.Field>
          </Form.Group>
        )}
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
