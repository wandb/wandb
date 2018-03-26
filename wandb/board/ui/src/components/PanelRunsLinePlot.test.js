import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Dropdown, Checkbox, Button} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';
import LinePlot from '../components/vis/LinePlot';
import HelpIcon from '../components/HelpIcon';
import './PanelRunsLinePlot';

describe('Panel components test', () => {
  const store = mockStore({
      global: {},
    }),
    PanelType = panelClasses['Run History Line Plot'];
  let props = {
      config: {
        aggregate: true,
      },
      data: {
        histories: {
          loading: false,
          data: [],
          maxRuns: 0,
          totalRuns: 0,
        },
        selectedRuns: [],
        base: ['test'],
        loading: false,
        filtered: [],
      },
      configMode: false,
      updateConfig: sinon.spy(),
    },
    container,
    dropdown,
    checkbox,
    range,
    button;

  it('checks if panel is rendered without config', () => {
    container = mount(
      <MockAppWrapper store={store}>
        <PanelType {...props} />
      </MockAppWrapper>,
    );

    expect(container.find('LinePlot')).to.have.length(1);
    expect(container.find('HelpIcon')).to.have.length(1);
    // header from config is not rendered
    expect(container.find('div.header')).to.have.length(0);

    // trigger button click event
    button = container.find(Button);
    button.at(1).simulate('click');
    // TODO: mock `addFilter` method

    expect(container.text()).to.have.string("This chart isn't configured yet");
  });

  it('checks if config panel is rendered', () => {
    props = {
      ...props,
      configMode: true,
      config: {
        ...props.config,
        key: 'value',
      },
      data: {
        ...props.data,
        selectedRuns: [{run1: 'test'}, {run2: 'test'}],
      },
    };
    container = mount(
      <MockAppWrapper store={store}>
        <PanelType {...props} />
      </MockAppWrapper>,
    );

    expect(container.find('div.header').text()).to.contain('No history data');

    // all dropdown controls are present
    dropdown = container.find(Dropdown);
    expect(dropdown).to.have.length(4);

    // simple validation for `updateConfig` method on all elements
    dropdown.forEach(node => {
      // trigger all dropdown change events
      node.simulate('change');
    });

    // trigger checkbox change event
    checkbox = container.find('input[type="checkbox"]');
    checkbox.simulate('change', {target: {checked: false}});

    // trigger range input change event
    range = container.find('input[type="range"]');
    range.simulate('change');

    // trigger button click event
    button = container.find(Button);
    button.simulate('click');

    expect(props.updateConfig.callCount).to.be.equal(7);
  });
});
