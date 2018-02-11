import _ from 'lodash';
import './json_parseMore.js';

export function JSONparseNaN(str) {
  return str ? JSON.parseMore(str) : str;
}
