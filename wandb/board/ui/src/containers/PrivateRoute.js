import React from 'react';
import {Route, Redirect} from 'react-router-dom';
import {connect} from 'react-redux';
const authed = state => ({user: state.global.user, auth: state.global.auth});

let authComponents = {};

function PrivateRoute({component: Component, user, auth, routeCache, ...rest}) {
  let AuthComponent;
  if (routeCache) {
    // This could really fuck you.
    AuthComponent = authComponents[Component.name];
    if (!AuthComponent) {
      AuthComponent = connect(authed)(Component);
      authComponents[Component.name] = AuthComponent;
    }
  } else {
    AuthComponent = connect(authed)(Component);
  }

  return (
    <Route
      {...rest}
      render={props =>
        auth.loggedIn() ? (
          <AuthComponent {...props} />
        ) : (
          <Redirect to={{pathname: '/login', state: {from: props.location}}} />
        )
      }
    />
  );
}

export default connect(authed)(PrivateRoute);
