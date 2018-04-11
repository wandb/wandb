export const TOGGLE_RUN_SELECTION = 'TOGGLE_RUN_SELECTION';
export const UPDATE_RUN_SELECTIONS = 'UPDATE_RUN_SELECTIONS';
export const UPDATE_JOB = 'UPDATE_JOB';
export const SET_FILTERS = 'SET_FILTERS';
export const SET_COLUMNS = 'MERGE_COLUMNS';
export const TOGGLE_COLUMN = 'TOGGLE_COLUMN';
export const ENABLE_COLUMN = 'ENABLE_COLUMN';
export const DISABLE_COLUMN = 'DISABLE_COLUMN';
export const CURRENT_PAGE = 'CURRENT_PAGE';
export const ADD_PLOT = 'ADD_PLOT';
export const REMOVE_PLOT = 'REMOVE_PLOT';
export const SET_SORT = 'SET_SORT';
export const SET_HIGHLIGHT = 'SET_HIGHLIGHT';

export const toggleRunSelection = (name, id) => {
  return {
    type: TOGGLE_RUN_SELECTION,
    name,
    id,
  };
};

export const updateRunSelection = selects => {
  return {
    type: UPDATE_RUN_SELECTIONS,
    selects,
  };
};

export const updateJob = id => {
  return {
    type: UPDATE_JOB,
    id,
  };
};

export const setHighlight = runId => {
  return {
    type: SET_HIGHLIGHT,
    runId,
  };
};

export const setFilters = (kind, filters) => {
  return {
    type: SET_FILTERS,
    kind,
    filters,
  };
};

export const setColumns = columns => {
  return {
    type: SET_COLUMNS,
    columns,
  };
};

export const toggleColumn = name => {
  return {
    type: TOGGLE_COLUMN,
    name,
  };
};

export const enableColumn = name => {
  return {
    type: ENABLE_COLUMN,
    name,
  };
};

export const disableColumn = name => {
  return {
    type: DISABLE_COLUMN,
    name,
  };
};

export const setSort = (name, ascending) => {
  return {
    type: SET_SORT,
    name,
    ascending,
  };
};

export const currentPage = (id, page) => {
  return {
    type: CURRENT_PAGE,
    id,
    page,
  };
};
