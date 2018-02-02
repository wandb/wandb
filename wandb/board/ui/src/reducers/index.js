import {combineReducers} from 'redux';
import {routerReducer} from 'react-router-redux';
import global from './global';
import runs from './runs';
import views from './views';
import location from './location';

const setupReducers = apolloClient =>
  combineReducers({
    global,
    runs,
    views,
    location,
    router: routerReducer,
  });

export default setupReducers;
