import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {
  addFilter,
  deleteFilter,
  editFilter,
  setFilterComponent,
} from '../actions/run';

function mapStateToProps(state, ownProps) {
  return {
    query: {
      ...ownProps.query,
      filters: state.runs.filters.filter,
      selections: state.runs.filters.select,
      sort: state.runs.sort,
    },
  };
}

export default connect(mapStateToProps, null);
