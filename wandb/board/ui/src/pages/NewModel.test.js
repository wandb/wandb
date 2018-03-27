import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {NewModel} from './NewModel';
import ModelEditor from '../components/ModelEditor';

describe('NewModel page components test', () => {
  const store = mockStore({global: {}}),
    match = {
      params: {},
    },
    user = {
      defaultFramework: 'keras',
    };
  let container,
    loading = false;

  it('renders without crashing', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <NewModel match={match} user={user} loading={loading} />
      </MockAppWrapper>,
    );
  });

  it('finds <ModelEditor /> component', () => {
    expect(container.find(ModelEditor)).toHaveLength(1);
  });
});
