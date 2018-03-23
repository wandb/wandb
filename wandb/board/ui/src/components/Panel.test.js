import React from 'react';
import Panel from './Panel';
import {Dropdown, Button} from 'semantic-ui-react';
import ContentLoader from 'react-content-loader';
import QueryEditor from '../components/QueryEditor';

describe('Panel components test', () => {
  const props = {
      editMode: false,
      query: {},
      updateType: sinon.spy(),
      updateSize: sinon.spy(),
      removePanel: sinon.spy(),
    },
    data = {
      columnNames: ['Description', 'Ran', 'Runtime', 'Config', 'Summary'],
      histories: [],
      history: [],
      historyKeys: [],
      base: [],
    };
  let container, dropdown, button;

  it('finds <ContentLoader /> component', () => {
    container = shallow(<Panel {...props} />);

    // check if content is loading
    expect(container.find(ContentLoader)).to.have.length(1);

    // check if loading is still in progress
    container.setProps({data: {}});
    expect(container.find(ContentLoader)).to.have.length(1);

    // loading is completed
    container.setProps({data: data});
    expect(container.find(ContentLoader)).to.have.length(0);

    // is dropdown for switching between charts present and working
    container.setProps({editMode: true});
    container.setState({configMode: true});
    dropdown = container.find(Dropdown);
    expect(container.find(Dropdown)).to.have.length(1);

    dropdown.simulate('change', null, {value: 'test'});
    expect(props.updateType.called).to.be.true;

    // is QueryEditor enabled
    container.setProps({viewType: 'dashboards'});
    expect(container.find(QueryEditor)).to.have.length(1);

    // expand method is called
    button = container.find('[icon="expand"]');
    button.simulate('click');
    expect(props.updateSize.called).to.be.true;

    // close panel is called
    button = container.find('[icon="close"]');
    button.simulate('click');
    expect(props.removePanel.called).to.be.true;
  });
});
