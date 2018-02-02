import React from 'react';
import {Switch, Route} from 'react-router';
import Routes from './routes';
import PrivateRoute from './containers/PrivateRoute';
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
    container = mount(
      <MockAppWrapper store={store}>
        <Routes />
      </MockAppWrapper>,
    );
  });

  // find at least 3 routes
  it('finds <Route /> component', () => {
    expect(container.find(Route)).to.have.lengthOf.above(2);
  });

  // PrivateRoute should not be present for anonymous user
  it("doesn't find <PrivateRoute /> component", () => {
    expect(container.find(PrivateRoute)).to.not.have.lengthOf.above(0);
  });

  // dispatch flash message
  it('check action before dispatching ', () => {
    expect(store.getActions())
      .to.be.an('array')
      .that.not.includes(expectedPayload);

    store.dispatch(setFlash(message));
  });

  // after dispatching
  it('check action after dispatching ', () => {
    expect(store.getActions())
      .to.be.an('array')
      .that.deep.includes(expectedPayload);
  });
});
