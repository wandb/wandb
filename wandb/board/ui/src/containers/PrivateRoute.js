import React from 'react';
import {Route, Redirect} from 'react-router-dom';
import {connect} from 'react-redux';
const authed = state => ({user: state.global.user, auth: state.global.auth});

function PrivateRoute({component: Component, user, auth, ...rest}) {
  let AuthComponent = connect(authed)(Component);
  return (
    <Route
      {...rest}
      render={props =>
        auth.loggedIn() ? (
          <AuthComponent {...props} />
        ) : (
          <Redirect to={{pathname: '/login', state: {from: props.location}}} />
        )}
    />
  );
}

export default connect(authed)(PrivateRoute);
