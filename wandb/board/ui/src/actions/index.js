export const NETWORK_ERROR = 'NETWORK_ERROR';
export const RESET_ERROR = 'RESET_ERROR';
export const SIGN_IN = 'SIGN_IN';
export const SIGN_OUT = 'SIGN_OUT';
export const FLASH = 'FLASH';
export const FULL_SCREEN = 'FULL_SCREEN';
export const GRAPHQL_STATUS = 'GRAPHQL_STATUS';

export const displayError = error => {
  return {
    type: NETWORK_ERROR,
    error,
  };
};

export const resetError = () => {
  return {
    type: RESET_ERROR,
  };
};

export const signIn = user => {
  return {
    type: SIGN_IN,
    user,
  };
};

export const signOut = () => {
  return {
    type: SIGN_OUT,
  };
};

export const setFlash = flash => {
  return {
    type: FLASH,
    flash,
  };
};

export const setFullScreen = fullScreen => {
  return {
    type: FULL_SCREEN,
    fullScreen,
  };
};

export const updateGraphqlStatus = status => {
  return {
    type: GRAPHQL_STATUS,
    status,
  };
};
