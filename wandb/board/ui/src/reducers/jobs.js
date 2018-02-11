import {UPDATE_JOB} from '../actions/run.js';

export default function jobs(state = {}, action) {
  switch (action.type) {
    case UPDATE_JOB:
      return {...state, currentJob: action.id};
    default:
      return state;
  }
}
