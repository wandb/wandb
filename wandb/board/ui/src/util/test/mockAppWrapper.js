import React from 'react';
import {ApolloClient} from 'apollo-client';
import {InMemoryCache} from 'apollo-cache-inmemory';
import {ApolloProvider} from 'react-apollo';
import {ApolloLink} from 'apollo-link';
import {Provider} from 'react-redux';
import {ConnectedRouter} from 'react-router-redux';
import createHistory from 'history/createMemoryHistory';

const link = new ApolloLink();
export const client = new ApolloClient({
  link: link,
  cache: new InMemoryCache(),
});

const MockAppWrapper = ({store, children}) => (
  <Provider store={store}>
    <ApolloProvider client={client}>
      <ConnectedRouter history={createHistory()}>{children}</ConnectedRouter>
    </ApolloProvider>
  </Provider>
);

export default MockAppWrapper;
