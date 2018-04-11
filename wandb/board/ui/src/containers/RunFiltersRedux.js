import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {setFilters} from '../actions/run';
import RunFilters from '../components/RunFilters';

function mapStateToProps(state, ownProps) {
  return {
    filters: state.runs.filters[ownProps.kind],
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({setFilters}, dispatch);
};

export default connect(mapStateToProps, mapDispatchToProps)(RunFilters);
