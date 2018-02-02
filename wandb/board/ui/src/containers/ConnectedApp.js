import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {setFlash} from '../actions';
import App from '../App';

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({setFlash}, dispatch);
};

function mapStateToProps(state, ownProps) {
  return {
    error: state.global.error,
    user: state.global.user,
    auth: state.global.auth,
    history: state.global.history,
  };
}

export default connect(mapStateToProps, mapDispatchToProps)(App);
