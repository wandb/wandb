import _ from 'lodash';

export function makeShouldUpdate(spec) {
  function checker(props, state, nextProps, nextState, extra) {
    let result = {};
    for (var key of _.keys(spec.props)) {
      let keySpec = spec.props[key];
      if (keySpec.deep) {
        result['prop:' + key] = _.isEqual(props[key], nextProps[key]);
      } else {
        result['prop:' + key] = props[key] === nextProps[key];
      }
    }
    for (var key of _.keys(spec.state)) {
      let keySpec = spec.state[key];
      if (keySpec.deep) {
        result['state:' + key] = _.isEqual(state[key], nextState[key]);
      } else {
        result['state:' + key] = state[key] === nextState[key];
      }
    }
    let shouldUpdate = _.values(result).some(o => !o);
    if (spec.debug && shouldUpdate) {
      let reason = _.map(result, (equal, key) => (!equal ? key : null))
        .filter(o => o)
        .join(', ');
      console.log(
        `Component (${spec.name} + ${extra ||
          ''}) shouldUpdate, [${reason}] changed.`,
      );
    }
    return shouldUpdate;
  }
  return checker;
}
