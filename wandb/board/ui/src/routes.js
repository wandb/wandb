import React from 'react';
import {Switch, Redirect} from 'react-router';
import ConnectedApp from './containers/ConnectedApp';
import Model from './pages/Model';
import Run from './pages/Run';
import Dashboard from './pages/Dashboard';
import NoMatch from './components/NoMatch';
import UserRoute from './containers/UserRoute';

export default ({auth}) => (
  <ConnectedApp>
    <Switch>
      <Redirect exact from="/" to="/board/default" />
      <UserRoute exact path="/dashboards" component={Dashboard} />
      <UserRoute path="/dashboards/edit" component={Dashboard} />
      <UserRoute path="/:entity/:model/edit" component={Model} />
      <UserRoute exact path="/:entity/:model/runs/:run" component={Run} />
      <UserRoute path="/:entity/:model/runs/:run/edit" component={Run} />
      <UserRoute exact path="/:entity/:model/runs" component={Model} />
      <UserRoute exact path="/:entity/:model" component={Model} />
      <UserRoute component={NoMatch} />
    </Switch>
  </ConnectedApp>
);
