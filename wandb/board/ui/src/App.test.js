import React from 'react';
import {Switch, Route} from 'react-router';
import Routes from './routes';
import PrivateRoute from './containers/PrivateRoute';
import UserRoute from './containers/UserRoute';
import MockAppWrapper from './util/test/mockAppWrapper';
import {setFlash} from './actions';
import {Transition, Message} from 'semantic-ui-react';

describe('App components test', () => {
  const store = mockStore({global: {}, location: {}}),
    message = {message: 'Test Finished', color: 'green'},
    expectedPayload = {
      type: 'FLASH',
      flash: message,
    };
  let container;

  it('renders without crashing', () => {
    container = render(
      <MockAppWrapper store={store}>
        <Routes />
      </MockAppWrapper>,
    );
  });

  it('finds footer text', () => {
    expect(container.text()).toContain('Weights & Biases');
  });

  // dispatch flash message
  it('check action before dispatching ', () => {
    expect(store.getActions()).not.toContain(expectedPayload);

    store.dispatch(setFlash(message));
  });

  // after dispatching
  it('check action after dispatching ', () => {
    expect(store.getActions()).toContainEqual(expectedPayload);
  });
});
