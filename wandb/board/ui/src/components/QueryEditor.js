import _ from 'lodash';
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
  setProject(project) {
    this.props.setQuery(update(this.query, {model: {$set: project}}));
  }

  setFilters(newFilters) {
    this.props.setQuery(
      update(this.query, {
        filters: {
          $set: newFilters,
        },
      })
    );
  }

  render() {
    const {query, allowProjectChange, runCount, mergeFilters} = this.props;
    this.query = query;
    let filters = this.query.filters;
    if (_.isObject(filters) && filters.op == null) {
      // Handle the old format.
      filters = Filter.fromOldQuery(_.values(filters));
    }
    if (filters == null) {
      filters = {
        op: 'OR',
        filters: [
          {
            op: 'AND',
            filters: [],
          },
        ],
      };
    }
    const entity = this.query.entity || this.props.defaultEntity;
    const project = Query.project(this.query) || this.props.defaultProject;

    return (
      <Form style={{marginBottom: 20}}>
        <Form.Group style={{marginLeft: 20}}>
          {allowProjectChange && (
            <Form.Field width={4}>
              <label>Project</label>
              <ProjectSelector
                entity={entity}
                value={project}
                onChange={project => this.setProject(project)}
              />
            </Form.Field>
          )}
          <Form.Field width={10}>
            <label>Filters</label>
            <RunFilters
              entityName={entity}
              projectName={project}
              filters={filters}
              mergeFilters={mergeFilters}
              filteredRunsCount={runCount}
              setFilters={(_, newFilters) => this.setFilters(newFilters)}
            />
          </Form.Field>
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
