import React from 'react';
import MockAppWrapper from '../util/test/mockAppWrapper';
import {Models} from './Models';
import {Header, Button} from 'semantic-ui-react';
import ErrorPage from '../components/ErrorPage';

describe('Models page components test', () => {
  const store = mockStore({global: {}}),
    props = {
      updateLocationParams: () => {},
      match: {params: {}},
      models: {
        edges: [
          {
            node: {
              id: 'id',
              description: 'description',
            },
          },
        ],
      },
    };
  let container;

  it('finds several key components', () => {
    window.Prism = {
      highlightAll: () => {},
    };

    container = shallow(<Models {...props} />);

    // test ErrorPage component
    expect(container.find(ErrorPage)).to.have.length(0);
    container.setProps({error: {}});
    expect(container.find(ErrorPage)).to.have.length(1);

    // finds Create new project button
    container.setProps({error: null, user: {}});
    expect(container.find(Button)).to.have.length(1);

    // finds Create new project button
    container.setProps({loading: false, models: {}});
    expect(container.find('a')).to.have.length(2);
    expect(container.find(Header).text()).toBe('Projects');
  });
});
