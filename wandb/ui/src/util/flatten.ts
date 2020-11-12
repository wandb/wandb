import isBuffer from 'is-buffer';

/* modified from https://github.com/hughsk/flat/blob/master/index.js */

// TODO: is this different from lodash's _.flatten? do we need both?
export function flatten(
  target: {[key: string]: any},
  opts: {[key: string]: any} = {}
) {
  const delimiter = opts.delimiter || '.';
  const maxDepth = opts.maxDepth;
  const output: {[key: string]: any} = {};

  function step(
    object: {[key: string]: any},
    prev?: string,
    currentDepth: number = 1
  ) {
    Object.keys(object).forEach(key => {
      const value = object[key];
      const isarray = opts.safe && Array.isArray(value);
      const isspecial = value && value._type;
      const type = Object.prototype.toString.call(value);
      const isbuffer = isBuffer(value);
      const isobject = type === '[object Object]' || type === '[object Array]';

      const newKey = prev ? prev + delimiter + key : key;

      if (
        !isarray &&
        !isbuffer &&
        !isspecial &&
        isobject &&
        Object.keys(value).length &&
        (!opts.maxDepth || currentDepth < maxDepth)
      ) {
        return step(value, newKey, currentDepth + 1);
      }

      output[newKey] = value;
    });
  }

  step(target);

  return output;
}
