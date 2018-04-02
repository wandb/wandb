import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Model} from './Model';
import {Container, Loader} from 'semantic-ui-react';
import ModelViewer from '../components/ModelViewer';
import ModelEditor from '../components/ModelEditor';
import ErrorPage from '../components/ErrorPage';

describe('Model page components test', () => {
  const store = mockStore({
      global: {},
      runs: {
        currentJob: 'test',
        filters: {
          filter: [],
        },
        sort: {},
        columns: {},
        pages: {},
      },
      views: {
        server: {},
        browser: {
          runs: {
            tabs: [],
          },
        },
        other: {
          runs: [],
        },
      },
    }),
    props = {
      match: {
        params: {},
        path: '/:entity/:model/edit',
      },
      model: {
        bucket: {
          createdAt: '2017-24-09T10:09:28.487559',
          name: 'tmp',
        },
        summaryMetrics: '{}',
      },
      updateLocationParams: () => {},
    };
  let container;

  beforeEach(() => {
    window.Prism = {
      highlightAll: () => {},
    };
  });

  it('renders without crashing', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <Model {...props} />
      </MockAppWrapper>,
    );
    expect(container.find(ModelViewer)).toHaveLength(1);
  });

  it('finds several key components', () => {
    container = shallow(<Model {...props} />);

    // test ErrorPage component
    expect(container.find(ErrorPage)).toHaveLength(0);
    container.setProps({error: {}});
    expect(container.find(ErrorPage)).toHaveLength(1);

    // test Loader component
    container.setProps({loading: true, error: null});
    expect(container.find(Loader)).toHaveLength(1);

    // test ModelEditor component
    container.setProps({loading: false, user: {}});
    expect(container.find(ModelEditor)).toHaveLength(1);
  });
});
