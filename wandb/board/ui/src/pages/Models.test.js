import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Models} from './Models';
import {Header} from 'semantic-ui-react';

describe('Models page components test', () => {
  const store = mockStore({global: {}}),
    match = {
      params: {},
    };
  let container;

  it('renders without crashing', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <Models match={match} />
      </MockAppWrapper>,
    );
  });

  it('finds <Header /> component', () => {
    expect(container.find(Header).text()).toBe('Projects');
  });
});
