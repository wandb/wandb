import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import DashboardWrapper, {Dashboard} from './Dashboard';
import Loader from '../components/Loader';
import ViewModifier from '../containers/ViewModifier';

describe('Dashboard page components test', () => {
  const store = mockStore({
      global: {},
      runs: {
        filters: {
          filter: {op: 'OR', filters: []},
          select: {op: 'OR', filters: []},
        },
      },
      views: {
        browser: {
          dashboards: {
            tabs: [],
          },
        },
        server: {
          dashboards: {},
        },
        other: {
          dashboards: {},
        },
      },
    }),
    props = {
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
        <DashboardWrapper {...props} />
      </MockAppWrapper>
    );
    expect(container.find(Loader)).toHaveLength(1);
  });

  it('shallow Dashboard wrapper component', () => {
    container = shallow(<DashboardWrapper {...props} />);
    expect(container.find(Dashboard)).toHaveLength(1);
  });
});
