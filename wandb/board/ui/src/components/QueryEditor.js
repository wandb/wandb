import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {Form, Checkbox} from 'semantic-ui-react';
import update from 'immutability-helper';
import * as Query from '../util/query';
import * as Filter from '../util/filters';
import * as RunHelpers from '../util/runhelpers';
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
    console.log('SETTING newFilters', newFilters);
    this.props.setQuery(
      update(this.query, {
        filters: {
          $set: newFilters,
        },
      }),
    );
  }

  render() {
    let {setQuery, runs, keySuggestions} = this.props;
    this.query = this.props.panelQuery || {};
    let strategy = this.query.strategy;
    if (strategy !== 'page' && strategy !== 'merge') {
      strategy = 'page';
    }
    this.filters = this.query.filters;
    if (_.isObject(this.filters) && this.filters.op == null) {
      // Handle the old format.
      this.filters = Filter.fromOldQuery(_.values(this.filters));
    }
    if (this.filters == null) {
      this.filters = {
        op: 'OR',
        filters: [
          {
            op: 'AND',
            filters: [],
          },
        ],
      };
    }
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
            {this.props.allowProjectChange && (
              <Form.Field width={4}>
                <label>Project</label>
                <ProjectSelector
                  entity={this.props.pageQuery.entity}
                  value={this.query.model || this.props.pageQuery.model}
                  onChange={project => this.setProject(project)}
                />
              </Form.Field>
            )}
            <Form.Field width={10}>
              <label>Filters</label>
              <RunFilters
                filters={this.filters}
                mergeFilters={this.props.pageQuery.filters}
                runs={runs}
                filteredRuns={this.props.filteredRuns}
                keySuggestions={keySuggestions}
                setFilters={(_, newFilters) => this.setFilters(newFilters)}
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
