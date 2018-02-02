import {UPDATE_LOCATION_PARAMS} from '../actions/location.js';

export default function jobs(state = {}, action) {
  switch (action.type) {
    case UPDATE_LOCATION_PARAMS:
      return {...state, params: action.params};
    default:
      return state;
  }
}
