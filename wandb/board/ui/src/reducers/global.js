import {NETWORK_ERROR, RESET_ERROR, SIGN_IN, SIGN_OUT, FLASH} from '../actions';
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
    default:
      return state;
  }
};
export default global;
