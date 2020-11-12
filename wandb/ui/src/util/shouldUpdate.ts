import React from 'react';
import _ from 'lodash';
import {difference} from '../util/data';

import config from '../config';

interface Props {
  [key: string]: any;
}
type State = Props;

interface Spec {
  name?: string; // Name of component for debugging
  deep?: string[]; // list of props to check with deep comparison
  ignore?: string[]; // list of props to ignore
  ignoreFunctions?: boolean; // ignore function props
  ignoreJSX?: boolean; // ignore JSX Element props
  debug?: boolean; // if true this prints the reason an update occurred
  verbose?: boolean; // if true (and debug is true), this prints changed props
}

// Make a componentShouldUpdate helper function.
// All props not in deep (or ignoreFunctions) will be checked with
// shallow comparison
export function makeShouldUpdate(spec: Spec) {
  function checker(props: Props, nextProps: Props, extra: string) {
    const result: {[key: string]: boolean} = {};

    const keys = _.keys(nextProps);
    for (const key of keys) {
      if (spec.ignoreFunctions && _.isFunction(nextProps[key])) {
        continue;
      }
      if (spec.ignoreJSX && React.isValidElement(nextProps[key])) {
        continue;
      }
      if (spec.ignore && _.includes(spec.ignore, key)) {
        continue;
      }
      if (spec.deep && _.includes(spec.deep, key)) {
        result[key] = _.isEqualWith(props[key], nextProps[key], (a, b) =>
          spec.ignoreFunctions && _.isFunction(b) ? true : undefined
        );
      } else {
        result[key] = props[key] === nextProps[key];
      }
    }

    const shouldUpdate = _.values(result).some(o => !o);
    if (spec.debug && shouldUpdate && config.ENABLE_DEBUG_FEATURES) {
      const reason = _.map(result, (equal, key) => (!equal ? key : null))
        .filter(o => o)
        .join(', ');
      if (spec.verbose) {
        console.group(`${spec.name}${extra ? ': ' + extra : ''} changed`);
        Object.keys(result).forEach(key => {
          if (!result[key]) {
            if (nextProps[key] == null) {
              console.log('null nextProps[key] ', nextProps[key]);
            } else if (props[key] == null) {
              console.log('null props[key] ', props[key]);
            } else {
              const diff = difference(props[key], nextProps[key]);
              console.groupCollapsed(key);
              console.log(`Before: `, props[key]);
              console.log(`After: `, nextProps[key]);
              if (_.keys(diff).length === 0) {
                console.log(
                  `Diff: `,
                  diff,
                  `NOTE: An empty diff is most likely the result of shallow compare. Consider adding the key: ${key} to the deep compares.`
                );
              } else {
                console.log(`Diff: `, diff);
              }
            }
            console.groupEnd();
          }
        });
        console.groupEnd();
      } else {
        console.log(
          `Component (${spec.name}:${extra ||
            ''}) shouldUpdate, [${reason}] changed`
        );
      }
    }
    return shouldUpdate;
  }
  return checker;
}

// compares both props and state. spec is the same as above, but 'deep' key is only used for props.
// use it like this:
//
// didPropsOrStateChange = makeDidPropsOrStateChange(mySpec);
// shouldComponentUpdate(nextProps, nextState) {
//   return this.didPropsOrStateChange([this.props, nextProps], [this.state, nextState], myExtraInfo)
// }
export function makeDidPropsOrStateChange(spec: Spec) {
  const didPropsUpdate = makeShouldUpdate(spec);
  const didStateUpdate = makeShouldUpdate(Object.assign({}, spec, {deep: []}));
  // props and state arguments are arrays of things to compare, like [this.props, nextProps]
  return function checker(props: Props, state?: State, extra?: string) {
    const propsUpdated = didPropsUpdate(
      props[0],
      props[1],
      `Props${extra ? ', ' + extra : ''}`
    );
    const stateUpdated =
      state &&
      didStateUpdate(state[0], state[1], `State${extra ? ', ' + extra : ''}`);
    return !!(propsUpdated || stateUpdated);
  };
}

type PropsAreEqualFn = (prevProps: Props, nextProps: Props) => boolean;

export function makePropsAreEqual(spec: Spec): PropsAreEqualFn {
  const didPropsUpdate = makeShouldUpdate(spec);
  return (prevProps: Props, nextProps: Props): boolean => {
    return !didPropsUpdate(prevProps, nextProps, 'Props');
  };
}
