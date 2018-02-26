import React from 'react';
import ReactDOM from 'react-dom';
import {ApolloProvider} from 'react-apollo';
import {ConnectedRouter} from 'react-router-redux';
import {Provider} from 'react-redux';
import registerServiceWorker from './registerServiceWorker';
import Routes from './routes';
import {connectStore, apolloClient, history} from './setup';
import './index.css';
import 'semantic/dist/semantic.min.css';

const user = {admin: false, entity: 'board'};

ReactDOM.render(
  <Provider store={connectStore(user)}>
    <ApolloProvider client={apolloClient}>
      <ConnectedRouter history={history}>
        <Routes />
      </ConnectedRouter>
    </ApolloProvider>
  </Provider>,
  document.getElementById('root'),
);
//TODO: do we want to use service workers in the board?
//registerServiceWorker();
