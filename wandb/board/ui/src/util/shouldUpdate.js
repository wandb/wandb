import _ from 'lodash';

// Make a componentShouldUpdate helper function.
// spec:
//   name: Name of component for debugging
//   extra: (passed to inner function) extra debugging info
//   deep: list of props to check with deep comparison
//   ignoreFunctions: ignore function props
//   debug: if true this prints the reason an update occurred
//
// All props not in deep (or ignoreFunctions) will be checked with
// shallow comparison
export function makeShouldUpdate(spec) {
  function checker(props, nextProps, extra) {
    let result = {};
    for (var key of spec.deep || []) {
      result[key] = _.isEqual(props[key], nextProps[key]);
    }
    for (var key of _.difference(_.keys(nextProps), spec.deep)) {
      let nextVal = nextProps[key];
      if (spec.ignoreFunctions && _.isFunction(nextVal)) {
        // pass
      } else {
        result[key] = props[key] === nextVal;
      }
    }

    let shouldUpdate = _.values(result).some(o => !o);
    if (spec.debug && shouldUpdate) {
      let reason = _.map(result, (equal, key) => (!equal ? key : null))
        .filter(o => o)
        .join(', ');
      console.log(
        `Component (${spec.name}:${extra ||
          ''}) shouldUpdate, [${reason}] changed.`,
      );
    }
    return shouldUpdate;
  }
  return checker;
}
