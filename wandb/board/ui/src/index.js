import React from 'react';
import ReactDOM from 'react-dom';
import {displayError} from './actions';
import {createStore, applyMiddleware, compose} from 'redux';
import {ApolloProvider} from 'react-apollo';
import Auth from './util/Auth';
import {BOARD} from './util/board';
import startTrace from './util/trace';
import setupReducers from './reducers';
import apolloClient, {connectStoreToApollo} from './util/apollo';
import createHistory from 'history/createBrowserHistory';
import {routerMiddleware, ConnectedRouter} from 'react-router-redux';
import {Provider} from 'react-redux';
import registerServiceWorker from './registerServiceWorker';
import subscribe from './subscriptions';
import {enableBatching} from 'redux-batched-actions';
import Routes from './routes';
import './index.css';
import 'semantic/dist/semantic.min.css';

const history = createHistory();
const reducers = setupReducers(apolloClient);
const auth = BOARD ? {} : new Auth('wandb.auth0.com', apolloClient);
const user = BOARD
  ? {admin: false, entity: 'board'}
  : JSON.parse(localStorage.getItem('user'));
const store = createStore(
  enableBatching(reducers),
  {global: {auth, history, user}}, // initial state
  compose(
    applyMiddleware(routerMiddleware(history)),
    typeof window.__REDUX_DEVTOOLS_EXTENSION__ !== 'undefined'
      ? window.__REDUX_DEVTOOLS_EXTENSION__()
      : f => f,
  ),
);
if (!BOARD) {
  subscribe(store, apolloClient);
}
auth.store = store;
connectStoreToApollo(store);

window.onerror = (msg, file, line, col, error) => {
  //TODO: do we want to diplay an exception all the time?
  //store.dispatch(displayError(error));
};
window.addEventListener('unhandledrejection', event => {
  store.dispatch(displayError([event.reason]));
});

history.listen(location => {
  window.ga('send', 'pageview', location.pathname);
  startTrace();
});
startTrace();

ReactDOM.render(
  <Provider store={store}>
    <ApolloProvider client={apolloClient}>
      <ConnectedRouter history={history}>
        <Routes auth={auth} />
      </ConnectedRouter>
    </ApolloProvider>
  </Provider>,
  document.getElementById('root'),
);
registerServiceWorker();
