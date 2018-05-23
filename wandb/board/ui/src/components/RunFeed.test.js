import React from 'react';
import {TableCell, TableHeaderCell} from 'semantic-ui-react';
import {RunFeed} from './RunFeed.js';
import {sortRuns} from '../util/runhelpers.js';

describe('Panel components test', () => {
  let container,
    runs = [
      {
        id: 'test2',
        description: 'desc2',
        config: {a: 5, b: 4, j: 'a'},
        summary: {c: 'string', d: 16},
      },
      {
        id: 'test3',
        description: 'desc3',
        config: {a: 17, b: 4, j: 'b'},
        summary: {c: 'another', d: 11},
      },
      {
        id: 'test1',
        description: 'desc1',
        config: {a: 17, b: 4, j: 'c'},
        summary: {c: 'another', d: 11},
      },
    ],
    sort = {
      ascending: true,
      name: 'config:a',
    };
  const props = {
    loading: false,
    project: {
      id: 'test',
    },
    data: {filtered: runs},
    config: {
      config: {
        auto: true,
      },
      summary: {
        auto: true,
      },
    },
    query: {},
    limit: 10,
    sort: {},
    setSort: sinon.spy(),
  };

  function getValues() {
    let values = [];
    container.find('RunFeedRow').forEach(row => {
      values.push(
        row
          .dive()
          .find(TableCell)
          .at(1)
          .children()
          .props().value
      );
    });
    return values;
  }

  it('sort option for RunFeed table', () => {
    container = shallow(<RunFeed {...props} />);

    // all header cells are displayed
    expect(
      container
        .find('RunFeedHeader')
        .dive()
        .find(TableHeaderCell)
    ).toHaveLength(7);

    // all table rows are present
    expect(container.find('RunFeedRunRow')).toHaveLength(runs.length);

    container.setProps({
      sort: sort,
    });

    // caret icon is present and in right direction
    expect(
      container
        .find('RunFeedHeader')
        .dive()
        .find(TableHeaderCell)
        .at(4)
        .findWhere(node => node.props().name === 'caret up')
    ).toHaveLength(1);

    // `setSort` action is called
    let cell = container
      .find('RunFeedHeader')
      .dive()
      .find(TableHeaderCell)
      .at(1);
    cell.simulate('click');
    expect(props.setSort.called).toBeTruthy();
  });
});
