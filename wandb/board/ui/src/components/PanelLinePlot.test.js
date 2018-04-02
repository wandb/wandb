import React from 'react';
import {Checkbox, Button} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';
import LinePlot from '../components/vis/LinePlot';
import './PanelLinePlot';

describe('Panel components test', () => {
  const store = mockStore({
      global: {},
    }),
    PanelType = panelClasses['LinePlot'],
    eventKeys = [
      '_runtime',
      '_timestamp',
      '_wandb',
      'system.cpu',
      'system.disk',
      'system.memory',
      'system.network.recv',
      'system.network.sent',
    ],
    events = [
      {
        'system.cpu': 16.04,
        'system.disk': 79.4,
        'system.memory': 60.34,
        'system.network.recv': 2509120,
        'system.network.sent': 2482980,
        _runtime: 8,
        _timestamp: 1520855563,
        _wandb: true,
      },
    ],
    lines = ['system.cpu', 'system.memory', 'system.disk'];
  let props = {
      config: {},
      updateConfig: sinon.spy(),
    },
    container,
    renderErrorChart,
    data,
    value,
    dropdown,
    button,
    range;

  beforeEach(() => {
    container = shallow(<PanelType {...props} />);
  });

  it('checks if panel is rendered without config', () => {
    expect(container.text()).toContain(
      'This plot type is not supported on this page',
    );

    container.setProps({data: {}});
    expect(container.text()).toContain(
      "This run doesn't have any history data",
    );

    data = {
      history: [{history: 'value'}],
      events: [{event: 'value'}],
    };
    container.setProps({
      data: data,
    });
    expect(container.text()).toContain("This chart isn't configured yet");

    data = {
      ...data,
      historyKeys: ['acc'],
      eventKeys: eventKeys,
    };
    container.setProps({
      data: data,
    });
    expect(container.text()).toContain('This chart has no data');
    expect(container.find('LinePlot').prop('xAxis')).toBeUndefined();

    data = {
      ...data,
      events: events,
    };
    container.setProps({
      data: data,
      config: {
        ...props.config,
        lines: lines,
      },
    });
    expect(container.find('LinePlot').prop('xAxis')).toBeDefined();
  });

  it('checks if config panel is rendered', () => {
    container.setProps({
      configMode: true,
      data: {
        historyKeys: [],
        eventKeys: eventKeys,
        events: events,
      },
      config: {
        lines: lines,
        yLogScale: false,
      },
    });

    // trigger X-Axis dropdown change event with exact param
    value = 'test';
    dropdown = container.find('FormDropdown[placeholder="X-Axis"]');
    dropdown.simulate('change', null, {value: value});
    expect(
      props.updateConfig.calledWith(sinon.match({xAxis: value})),
    ).toBeTruthy();

    // trigger Lines dropdown change event with exact param
    dropdown = container.find('FormDropdown[placeholder="metrics"]');
    dropdown.simulate('change', null, {value: value});
    expect(
      props.updateConfig.calledWith(sinon.match({lines: value})),
    ).toBeTruthy();

    // trigger Button log click event to switch flag
    button = container.find('Button');
    button.simulate('click', null, {value: true});
    expect(
      props.updateConfig.calledWith(
        sinon.match({yLogScale: !props.config.yLogScale}),
      ),
    ).toBeTruthy();

    // trigger Smoothness range input change event
    value = 1;
    range = container.find('input[type="range"]');
    range.simulate('change', {target: {value: value}});
    expect(
      props.updateConfig.calledWith(sinon.match({smoothingWeight: value})),
    ).toBeTruthy();
  });
});
