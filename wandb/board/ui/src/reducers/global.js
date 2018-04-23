import {
  NETWORK_ERROR,
  RESET_ERROR,
  SIGN_IN,
  SIGN_OUT,
  FLASH,
  FULL_SCREEN,
  GRAPHQL_STATUS,
} from '../actions';
import update from 'immutability-helper';

const global = (state = {}, action) => {
  switch (action.type) {
    case NETWORK_ERROR:
      console.error('Network error', action);
      return update(state, {$merge: {error: action.error}});
    case RESET_ERROR:
      return update(state, {$merge: {error: null}});
    case SIGN_IN:
      return update(state, {$merge: {user: action.user}});
    case SIGN_OUT:
      return update(state, {
        $merge: {
          user: {anon: true, getToken: () => new Promise(r => r(false))},
        },
      });
    case FLASH:
      return update(state, {$merge: {flash: action.flash}});
    case FULL_SCREEN:
      return update(state, {$merge: {fullScreen: action.fullScreen}});
    case GRAPHQL_STATUS:
      return update(state, {$merge: {graphqlStatus: action.status}});
    default:
      return state;
  }
};
export default global;
