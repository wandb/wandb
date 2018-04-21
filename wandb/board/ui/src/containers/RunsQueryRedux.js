import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';

function mapStateToProps(state, ownProps) {
  return {
    filters: state.runs.filters.filter,
  };
}

export default connect(mapStateToProps, null);
