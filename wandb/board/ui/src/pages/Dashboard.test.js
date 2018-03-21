import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Dashboard} from './Dashboard';
import {Loader} from 'semantic-ui-react';

describe('Dashboard page components test', () => {
  const store = mockStore({
      global: {},
      runs: {
        filters: {
          filter: [],
        },
      },
      views: {
        other: {
          dashboards: {},
        },
      },
    }),
    props = {
      loading: true,
      data: {
        selectedRuns: [],
      },
      match: {
        params: {},
        path: '/:entity/:model/dashboards',
      },
    };
  let container;

  it('finds <Loader /> component', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <Dashboard {...props} />
      </MockAppWrapper>,
    );
    expect(container.find(Loader)).to.have.length(1);
  });
});
