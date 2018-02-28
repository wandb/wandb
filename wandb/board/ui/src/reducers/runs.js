import update from 'immutability-helper';
import _ from 'lodash';
import {
  TOGGLE_RUN_SELECTION,
  UPDATE_RUN_SELECTIONS,
  UPDATE_JOB,
  UPDATE_LOSS,
  ADD_FILTER,
  DELETE_FILTER,
  EDIT_FILTER,
  SET_FILTER_COMPONENT,
  CLEAR_FILTERS,
  SET_COLUMNS,
  TOGGLE_COLUMN,
  ENABLE_COLUMN,
  DISABLE_COLUMN,
  SET_SORT,
  CURRENT_PAGE,
  SET_HIGHLIGHT,
} from '../actions/run.js';

let nextFilterID = 0;

export default function runs(
  state = {
    selected: {},
    filters: {filter: {}, select: {}},
    highlight: null,
    editingFilter: null,
    columns: {},
    plots: [],
    sort: {},
    pages: {},
  },
  action,
) {
  switch (action.type) {
    case TOGGLE_RUN_SELECTION:
      let selected = {...state.selected};
      if (state.selected[action.name]) {
        delete selected[action.name];
      } else {
        selected[action.name] = action.id;
      }
      return {...state, selected: selected};
    case UPDATE_RUN_SELECTIONS:
      selected = [];
      action.selects.forEach((run, i) => {
        selected[run] = true;
      });
      return {...state, selected: selected};
    case UPDATE_LOSS:
      return {...state, [action.id]: action.loss};
    case UPDATE_JOB:
      return {...state, currentJob: action.id};
    case ADD_FILTER:
      // We just change the value if we already have filter for this key/op
      let filter = _.find(
        state.filters[action.kind],
        (filter, filterID) =>
          filter.key.section === action.key.section &&
          filter.key.value === action.key.value &&
          filter.op === action.op,
      );
      if (action.value === null) {
        // Remove filter if value is null
        if (!filter) {
          return state;
        } else {
          return update(state, {
            filters: {[action.kind]: {$unset: [filter.id]}},
          });
        }
      }
      let filterID;
      if (filter) {
        filterID = filter.id;
      } else {
        filterID = nextFilterID;
        nextFilterID++;
      }
      return update(state, {
        filters: {
          [action.kind]: {
            [filterID]: {
              $set: {
                id: filterID,
                key: action.key,
                op: action.op,
                value: action.value,
              },
            },
          },
        },
      });
    case DELETE_FILTER:
      return update(state, {filters: {[action.kind]: {$unset: [action.id]}}});
    case SET_FILTER_COMPONENT:
      return update(state, {
        filters: {
          [action.kind]: {
            [action.id]: {[action.component]: {$set: action.value}},
          },
        },
      });
    case CLEAR_FILTERS:
      nextFilterID = 0;
      return update(state, {
        filterModel: {$set: action.filterModel},
        filters: {$set: {filter: {}, select: {}}},
      });
    case SET_HIGHLIGHT:
      return update(state, {highlight: {$set: action.runId}});
    case SET_COLUMNS:
      return {
        ...state,
        columns: action.columns,
      };
    case TOGGLE_COLUMN:
      return {
        ...state,
        columns: {
          ...state.columns,
          [action.name]: !state.columns[action.name],
        },
      };
    case ENABLE_COLUMN:
      return {
        ...state,
        columns: {...state.columns, [action.name]: true},
      };
    case DISABLE_COLUMN:
      return {
        ...state,
        columns: {...state.columns, [action.name]: false},
      };
    case SET_SORT:
      return {
        ...state,
        sort: action,
      };
    case CURRENT_PAGE:
      return {
        ...state,
        pages: {
          ...state.pages,
          [action.id]: {
            current: action.page > 0 ? action.page : 1,
          },
        },
      };
    default:
      return state;
  }
}
