export const SET_SERVER_VIEWS = 'SET_SERVER_VIEWS';
export const ADD_VIEW = 'ADD_VIEW';
export const SET_ACTIVE_VIEW = 'SET_ACTIVE_VIEW';
export const CHANGE_VIEW_NAME = 'CHANGE_VIEW_NAME';
export const REMOVE_VIEW = 'REMOVE_VIEW';
export const ADD_PANEL = 'ADD_PANEL';
export const REMOVE_PANEL = 'REMOVE_PANEL';
export const UPDATE_PANEL = 'UPDATE_PANEL';

export const setServerViews = (views, browserOnly) => {
  return {
    type: SET_SERVER_VIEWS,
    views,
    browserOnly,
  };
};

export const addView = (viewType, viewName, panels) => {
  return {
    type: ADD_VIEW,
    viewType,
    viewName,
    panels,
  };
};

export const setActiveView = (viewType, viewId) => {
  return {
    type: SET_ACTIVE_VIEW,
    viewType,
    viewId,
  };
};

export const changeViewName = (viewType, viewId, viewName) => {
  return {
    type: CHANGE_VIEW_NAME,
    viewType,
    viewName,
    viewId,
  };
};

export const removeView = (viewType, viewId) => {
  return {
    type: REMOVE_VIEW,
    viewType,
    viewId,
  };
};

export const addPanel = (viewType, viewId, panel) => {
  return {
    type: ADD_PANEL,
    viewType,
    viewId,
    panel,
  };
};

export const removePanel = (viewType, viewId, panelIndex) => {
  return {
    type: REMOVE_PANEL,
    viewType,
    viewId,
    panelIndex,
  };
};

export const updatePanel = (viewType, viewId, panelIndex, panel) => {
  return {
    type: UPDATE_PANEL,
    viewType,
    viewId,
    panelIndex,
    panel,
  };
};
