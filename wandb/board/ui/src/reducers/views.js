import update from 'immutability-helper';
import _ from 'lodash';
import {
  RESET_VIEWS,
  SET_SERVER_VIEWS,
  SET_BROWSER_VIEWS,
  ADD_VIEW,
  UPDATE_VIEW,
  SET_ACTIVE_VIEW,
  MOVE_ACTIVE_VIEW_LEFT,
  MOVE_ACTIVE_VIEW_RIGHT,
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
  return {
    run: viewTypeDefaults(),
    runs: viewTypeDefaults(),
    dashboards: viewTypeDefaults(),
  };
}

function fixupViews(views) {
  if (_.isArray(views.dashboards)) {
    // This fixes some data that was added during early dashboard
    // development. Should be very uncommon and not affect customer
    // data.
    return update(views, {
      dashboards: {
        views: {$set: views.dashboards},
        tabs: {$set: _.keys(views.dashboards.views)},
      },
    });
  }
  return views;
}

function defaultViews() {
  return {
    server: copyDefaults(),
    browser: copyDefaults(),
    other: {
      run: {activeView: null},
      runs: {activeView: null},
      dashboards: {activeView: null},
    },
  };
}

export default function views(state = defaultViews(), action) {
  switch (action.type) {
    case RESET_VIEWS:
      return update(state, {$set: defaultViews()});
    case SET_SERVER_VIEWS:
      return update(state, {server: {$set: fixupViews(action.views)}});
    case SET_BROWSER_VIEWS:
      return update(state, {browser: {$set: fixupViews(action.views)}});
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
    case UPDATE_VIEW:
      return update(state, {
        browser: {
          [action.viewType]: {
            views: {
              [action.viewId]: {
                config: {$set: action.panels},
              },
            },
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
    case MOVE_ACTIVE_VIEW_LEFT: {
      let activeViewId = state.other[action.viewType].activeView;
      if (_.isNil(activeViewId)) {
        return state;
      }
      let tabs = state.browser[action.viewType].tabs;
      let curPos = _.indexOf(tabs, activeViewId);
      if (curPos === 0) {
        // I can't go left anymore!
        return state;
      }
      let swapPos = curPos - 1;
      let swapViewId = tabs[swapPos];
      return update(state, {
        browser: {
          [action.viewType]: {
            tabs: {
              [swapPos]: {$set: activeViewId},
              [curPos]: {$set: swapViewId},
            },
          },
        },
      });
    }
    case MOVE_ACTIVE_VIEW_RIGHT: {
      console.log('Hello everyone');
      console.log(state);
      console.log(action.viewType);
      let activeViewId = state.other[action.viewType].activeView;
      if (_.isNil(activeViewId)) {
        console.log('B1');
        return state;
      }
      let tabs = state.browser[action.viewType].tabs;
      let curPos = _.indexOf(tabs, activeViewId);
      if (curPos === tabs.length - 1) {
        console.log('B2');

        // I can't go right anymore!
        return state;
      }
      console.log('B3');

      let swapPos = curPos + 1;
      let swapViewId = tabs[swapPos];
      return update(state, {
        browser: {
          [action.viewType]: {
            tabs: {
              [swapPos]: {$set: activeViewId},
              [curPos]: {$set: swapViewId},
            },
          },
        },
      });
    }

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
