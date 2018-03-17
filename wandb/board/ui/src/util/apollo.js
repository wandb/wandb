import ApolloClient from 'apollo-client';
import {ApolloLink, Observable} from 'apollo-link';
import {InMemoryCache} from 'apollo-cache-inmemory';
import {createHttpLink} from 'apollo-link-http';
import {onError} from 'apollo-link-error';
import {displayError, setFlash} from '../actions';
import {push} from 'react-router-redux';
import queryString from 'query-string';
import {BOARD} from './board';

let dispatch = null;

const SERVERS = {
  production: 'https://api.wandb.ai/quiver',
  // development: 'http://gql.test/graphql',
  development: 'http://gql.test/quiver',
  devprod: 'https://api.wandb.ai/quiver',
  board:
    process.env.NODE_ENV === 'production'
      ? 'http://localhost:7177/graphql'
      : '/graphql',
};
export const SERVER =
  process.env.REACT_APP_BACKEND_URL ||
  SERVERS[process.env.REACT_APP_SERVER || process.env.NODE_ENV];
const httpLink = createHttpLink({uri: SERVER});

const authMiddleware = new ApolloLink((operation, forward) => {
  if (BOARD) return forward(operation);
  let qs = queryString.parse(document.location.search);
  let token = qs.token || localStorage.getItem('id_token');

  if (token) {
    operation.setContext(({headers = {}}) => ({
      headers: {
        ...headers,
        authorization: `Bearer ${token}`,
      },
    }));
  }

  return forward(operation);
});

const stackdriverMiddleware = new ApolloLink((operation, forward) => {
  let qs = queryString.parse(document.location.search);

  if (qs.trace) {
    console.log('DOING TRACE');
    let count = parseInt(localStorage.getItem('request_count'), 10);
    operation.setContext(({headers = {}}) => ({
      headers: {
        ...headers,
        'X-Cloud-Trace-Context':
          localStorage.getItem('page_id') + '/' + count + ';o=1',
      },
    }));
    localStorage.setItem('request_count', count + 1);
  }

  return forward(operation);
});

const userTimingMiddleware = new ApolloLink((operation, forward) => {
  const uuid = localStorage.getItem('page_id');
  return forward(operation).map(data => {
    if (window.performance && !BOARD) {
      setTimeout(() => {
        try {
          window.performance.mark(uuid + '-end');
          window.performance.measure(
            operation.operationName,
            uuid + '-start',
            uuid + '-end',
          );
          const measure = window.performance.getEntriesByName(
            operation.operationName,
          )[0];
          window.ga(
            'send',
            'timing',
            operation.operationName,
            measure.duration,
          );
        } catch (e) {
          console.warn('unable to time pageview', e);
        }
      });
    }
    return data;
  });
});

const errorLink = onError(({networkError, graphQLErrors}, store) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(error => {
      let {message, code} = error;
      if (code === 401) {
        localStorage.removeItem('id_token');
        if (document.location.pathname !== '/login') {
          localStorage.setItem('redirect', document.location.pathname);
        }
        dispatch(push('/login'));
      } else {
        console.error(`GraphQL error ${message} (${code}):`);
        dispatch(displayError(error));
      }
    });
  }
  if (networkError) {
    console.error(`Network Error: ${networkError}`);
    if (networkError.result) {
      console.error(networkError.result.errors);
    }

    dispatch(setFlash({message: 'Backend Unavailable', color: 'red'}));
  }
});

const link = ApolloLink.from([
  authMiddleware,
  stackdriverMiddleware,
  userTimingMiddleware,
  errorLink,
  httpLink,
]);

const apolloClient = new ApolloClient({
  link: link,
  cache: new InMemoryCache({
    dataIdFromObject: object => object.id,
  }),
});

export const connectStoreToApollo = store => {
  dispatch = store.dispatch;
};

export default apolloClient;
