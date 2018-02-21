import update from 'immutability-helper';
import _ from 'lodash';
import {
  SET_SERVER_VIEWS,
  ADD_VIEW,
  SET_ACTIVE_VIEW,
  CHANGE_VIEW_NAME,
  REMOVE_VIEW,
  ADD_PANEL,
  REMOVE_PANEL,
  UPDATE_PANEL,
} from '../actions/view.js';

function getAvailableViewId(views) {
  for (let i = 0; i < 1000000; i++) {
    if (!views[i]) {
      return i;
    }
  }
  throw new Error("Didn't find available viewId??");
}

function viewTypeDefaults() {
  return {views: {}, tabs: []};
}

function copyDefaults() {
  return {run: viewTypeDefaults(), runs: viewTypeDefaults()};
}

export default function views(
  state = {
    server: copyDefaults(),
    browser: copyDefaults(),
    other: {run: {activeView: null}, runs: {activeView: null}},
  },
  action,
) {
  switch (action.type) {
    case SET_SERVER_VIEWS:
      let updates = {};
      if (!action.browserOnly) {
        updates.server = {$set: action.views};
      }
      updates.browser = {$set: action.views};
      return update(state, updates);
    case ADD_VIEW:
      let viewId = getAvailableViewId(state.browser[action.viewType].views);
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {
              [viewId]: {
                $set: {
                  name: action.viewName,
                  defaults: [],
                  config: action.panels,
                },
              },
            },
            tabs: {$push: [viewId]},
          },
        },
        other: {
          [action.viewType]: {
            activeView: {$set: viewId},
          },
        },
      });
    case SET_ACTIVE_VIEW:
      return update(state, {
        other: {
          [action.viewType]: {
            activeView: {$set: action.viewId},
          },
        },
      });
    case CHANGE_VIEW_NAME:
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {[action.viewId]: {name: {$set: action.viewName}}},
          },
        },
      });
    case REMOVE_VIEW:
      let tabIndex = _.findIndex(
        state.browser[action.viewType].tabs,
        o => o === action.viewId,
      );
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {$unset: [action.viewId]},
            tabs: {
              $splice: [[tabIndex, 1]],
            },
          },
        },
      });
    case ADD_PANEL:
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {[action.viewId]: {config: {$push: [action.panel]}}},
          },
        },
      });
    case REMOVE_PANEL:
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {
              [action.viewId]: {config: {$splice: [[action.panelIndex, 1]]}},
            },
          },
        },
      });
    case UPDATE_PANEL:
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {
              [action.viewId]: {
                config: {[action.panelIndex]: {$set: action.panel}},
              },
            },
          },
        },
      });
    default:
      return state;
  }
}
