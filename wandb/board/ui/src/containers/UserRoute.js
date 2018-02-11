import React from 'react';
import {Route} from 'react-router-dom';
import {connect} from 'react-redux';
const props = state => ({user: state.global.user});

function UserRoute({component: Component, user, ...rest}) {
  let UserComponent = connect(props)(Component);
  return <Route {...rest} render={props => <UserComponent {...props} />} />;
}

export default UserRoute;
