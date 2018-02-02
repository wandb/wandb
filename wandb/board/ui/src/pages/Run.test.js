import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Run} from './Run';
import {Loader} from 'semantic-ui-react';
import RunViewer from '../components/RunViewer';
import RunEditor from '../components/RunEditor';

describe('Run page components test', () => {
  const store = mockStore({global: {}}),
    model = {
      bucket: {
        createdAt: '2017-24-09T10:09:28.487559',
        exampleTable: '[]',
        exampleTableColumns: '[]',
        exampleTableTypes: '{}',
        history: [],
        logLines: {
          edges: [],
        },
        summaryMetrics: '{}',
      },
    },
    loss = [],
    user = {};
  let container,
    loading = true,
    match = {
      params: {},
      path: '/:entity/:model/runs/:run',
    };

  beforeEach(() => {
    container = mount(
      <MockAppWrapper store={store}>
        <Run
          match={match}
          model={model}
          bucket={model.bucket}
          loss={loss}
          user={user}
          loading={loading}
        />
      </MockAppWrapper>,
    );
  });

  it('finds <Loader /> component', () => {
    expect(container.find(Loader)).to.have.length(1);
    loading = false;
  });

  it('finds <RunViewer /> component', () => {
    expect(container.find(RunViewer)).to.have.length(1);
    match.path = '/:entity/:model/runs/:run/edit';
  });

  it('finds <RunEditor /> component', () => {
    expect(container.find(RunEditor)).to.have.length(1);
  });
});
