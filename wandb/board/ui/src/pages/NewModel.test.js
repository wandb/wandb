import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import NewModelConnected, {NewModel} from './NewModel';
import ModelEditor from '../components/ModelEditor';

describe('NewModel page components test', () => {
  const store = mockStore({global: {}}),
    props = {
      match: {
        params: {},
      },
      user: {
        defaultFramework: 'keras',
      },
      loading: true,
      dispatch: sinon.spy(),
    };
  let container;

  it('renders without crashing', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <NewModelConnected {...props} />
      </MockAppWrapper>,
    );

    expect(container.find(ModelEditor)).to.have.length(1);
  });

  it('renders without crashing', () => {
    window.Prism = {
      highlightAll: () => {},
    };

    container = shallow(<NewModel {...props} />);

    const addModel = jest
      .spyOn(container.instance(), 'addModel')
      .bind({props: props});

    container.setProps({loading: false});
    expect(container.find(ModelEditor)).to.have.length(1);

    addModel({entityName: 'test', name: 'model'});
    expect(props.dispatch.calledOnce).to.be.true;
  });
});
