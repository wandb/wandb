import update, {Query} from 'immutability-helper';
import * as _ from 'lodash';
import * as Filter from './filters';
import * as Run from './runs';

// Selections control the set of runs that are highlighted in charts and checked in the runs
// table.
// - Currently, highlighting/unhighlighting on charts does not affect the state of previously checked
//   or unchecked runs. They will be permantently selected or unselected until the checked state changes
//   or the user chooses select all or select none.
// - Selections implements the Filter interface. It is always a top-level OR having at least one
//   filter.
//   - The first filter in the OR is always an AND, and contains bound selections (e.g. config:lr > 0.7)
//     and individual run deselections (e.g. run:id != 'a4bcce')
//   - individual run selections are the remaining children of the OR (e.g. run:id = 'a4bcce')

export interface Selection {
  readonly op: 'OR';
  readonly filters: SelectionInner[];
}

type BoundOp = '<=' | '>=';

interface SelectionInner {
  readonly op: 'AND';
  readonly filters: Filter.IndividualFilter[];
}

export function all(): Selection {
  return {
    op: 'OR',
    filters: [
      {
        op: 'AND',
        filters: [],
      },
    ],
  };
}

export function none(): Selection {
  return {
    op: 'OR',
    filters: [
      {
        op: 'AND',
        filters: [{key: {section: 'run', name: 'id'}, op: '!=', value: '*'}],
      },
    ],
  };
}

function findIndex(selection: Selection, key: Run.Key, op: BoundOp): number {
  return _.findIndex(selection.filters[0].filters, {key, op});
}

export function bounds(
  selection: Selection,
  key: Run.Key,
): [number | null, number | null] {
  let lowerValue = null;
  let upperValue = null;
  const lowerIndex = findIndex(selection, key, '>=');
  const upperIndex = findIndex(selection, key, '<=');
  if (lowerIndex !== -1) {
    const val = selection.filters[0].filters[lowerIndex].value;
    if (typeof val === 'number') {
      lowerValue = val;
    }
  }
  if (upperIndex !== -1) {
    const val = selection.filters[0].filters[upperIndex].value;
    if (typeof val === 'number') {
      upperValue = val;
    }
  }
  return [lowerValue, upperValue];
}

export class Update {
  // TODO: need ability to clear bounds when deselecting on scatter plot
  static addBound(
    selection: Selection,
    key: Run.Key,
    op: BoundOp,
    value: number,
  ): Selection {
    // All bounds are added in the first AND group. If we already have this bound, we modify it.
    const filter = {key, op, value};
    const selectNoneIndex = _.findIndex(selection.filters[0].filters, {
      key: {section: 'run', name: 'id'},
      op: '!=',
      value: '*',
    });
    // Remove the none selection if present.
    if (selectNoneIndex !== -1) {
      selection = Filter.Update.groupRemove(selection, [0], selectNoneIndex);
    }
    const index = findIndex(selection, key, op);
    if (index === -1) {
      return Filter.Update.groupPush(selection, [0], filter);
    } else {
      return Filter.Update.setFilter(selection, [0, index], filter);
    }
  }

  static select(selection: Selection, id: string): Selection {
    // Removes a deselection if present and adds a selection. The selection is added
    // as a new child of the OR.
    const key: Run.Key = {section: 'run', name: 'id'};
    const deselectIndex = _.findIndex(selection.filters[0].filters, {
      key,
      op: '!=',
      value: id,
    });
    if (deselectIndex !== -1) {
      selection = Filter.Update.groupRemove(selection, [0], deselectIndex);
    }
    selection = Filter.Update.groupPush(selection, [], {
      key,
      op: '=',
      value: id,
    });
    return selection;
  }

  static deselect(selection: Selection, id: string): Selection {
    // Inverse of select. The deselect is added to the first AND.
    const key: Run.Key = {section: 'run', name: 'id'};
    const selectIndex = _.findIndex(selection.filters, {
      key,
      op: '=',
      value: id,
    });
    if (selectIndex !== -1) {
      selection = Filter.Update.groupRemove(selection, [], selectIndex);
    }
    selection = Filter.Update.groupPush(selection, [0], {
      key,
      op: '!=',
      value: id,
    });
    return selection;
  }
}
