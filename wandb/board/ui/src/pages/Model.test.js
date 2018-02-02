import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Model} from './Model';
import Markdown from '../components/Markdown';
import Jobs from '../containers/Jobs';

describe('Model page components test', () => {
  const store = mockStore({
      global: {},
      runs: {
        currentJob: 'test',
      },
    }),
    match = {
      params: {},
      path: '/:entity/:model',
    },
    model = {
      bucket: {
        createdAt: '2017-24-09T10:09:28.487559',
        name: 'tmp',
      },
      summaryMetrics: '{}',
    };
  let container;

  beforeEach(() => {
    container = mount(
      <MockAppWrapper store={store}>
        <Model match={match} model={model} />
      </MockAppWrapper>,
    );
  });

  it('finds <Markdown /> inside component', () => {
    expect(container.find(Markdown)).to.have.length(1);
  });
});
