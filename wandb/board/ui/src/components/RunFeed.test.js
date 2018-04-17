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
        config: {
          epochs: 2,
        },
        tags: [],
      },
      {
        id: 'test3',
        description: 'desc3',
        config: {
          epochs: 3,
        },
        tags: [],
      },
      {
        id: 'test1',
        description: 'desc1',
        config: {
          epochs: 1,
        },
        tags: [],
      },
    ],
    sort = {
      ascending: true,
      name: 'config:epochs',
      type: 'SET_SORT',
    };
  const props = {
    loading: false,
    project: {
      id: 'test',
    },
    runs: runs,
    columns: {
      Description: {},
      'config:epochs': {},
    },
    columnNames: ['Description', 'config:epochs'],
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
          .props().value,
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
        .find(TableHeaderCell),
    ).toHaveLength(props.columnNames.length);

    // all table rows are present
    expect(container.find('RunFeedRow')).toHaveLength(runs.length);
    // rows are unsorted
    expect(getValues()).toEqual([2, 3, 1]);

    runs = sortRuns(sort, runs);
    container.setProps({
      sort: sort,
      runs: runs,
    });
    // caret icon is present and in right direction
    expect(
      container
        .find('RunFeedHeader')
        .dive()
        .find(TableHeaderCell)
        .at(1)
        .findWhere(node => node.props().name === 'caret up'),
    ).toHaveLength(1);

    // `setSort` action is called
    let cell = container
      .find('RunFeedHeader')
      .dive()
      .find(TableHeaderCell)
      .at(1);
    cell.simulate('click');
    expect(props.setSort.called).toBeTruthy();

    // row order is changed and ascending
    expect(getValues()).toEqual([1, 2, 3]);

    sort.ascending = false;
    runs = sortRuns(sort, runs);
    container.setProps({
      sort: sort,
      runs: runs,
      update: true,
    });
    // sort order is changed again
    expect(
      container
        .find('RunFeedHeader')
        .dive()
        .find(TableHeaderCell)
        .at(1)
        .findWhere(node => node.props().name === 'caret down'),
    ).toHaveLength(1);

    // row order is descending
    expect(getValues()).toEqual([3, 2, 1]);
  });
});
