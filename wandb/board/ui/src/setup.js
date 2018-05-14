import apolloClient, {connectStoreToApollo} from './util/apollo';
import createHistory from 'history/createBrowserHistory';
import setupReducers from './reducers';
import {enableBatching} from 'redux-batched-actions';
import {routerMiddleware} from 'react-router-redux';
import {createStore, applyMiddleware, compose} from 'redux';

export const history = createHistory();
export const reducers = setupReducers(apolloClient);
export const connectStore = (user, auth = {loggedIn: () => true}) => {
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
  auth.store = store;
  window.addEventListener('unhandledrejection', event => {
    // NOTE there is no need for this error to be displayed in flash message
    // as it is caught by apollo's `errorLink`
    console.error('Unhandled rejection', event.reason);
  });
  connectStoreToApollo(store);
  return store;
};
export {apolloClient};
