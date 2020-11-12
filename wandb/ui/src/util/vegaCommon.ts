import * as Obj from '../util/obj';
import * as _ from 'lodash';
import {VisualizationSpec} from 'react-vega';
import {flatten} from '../util/flatten';

export interface FieldSettings {
  [key: string]: string;
}
export interface UserSettings {
  fieldSettings: FieldSettings;
  stringSettings: FieldSettings;
}

/* eslint-enable no-template-curly-in-string */
/**
 * For renderer
 */

export interface FieldRef {
  type: 'field' | 'string';
  name: string;
  raw: string;
  default?: string;
}

function toRef(s: string): FieldRef | null {
  const [refName, rest, dflt] = s.split(':', 3);
  if (rest == null) {
    return null;
  }
  switch (refName) {
    case 'field':
      return {type: 'field', name: rest, raw: s};
    case 'string':
      return {type: 'string', name: rest, default: dflt, raw: s};
    default:
      return null;
  }
}
export function extractRefs(s: string): FieldRef[] {
  const match = s.match(new RegExp(`\\$\\{.*?\\}`, 'g'));
  if (match == null) {
    return [];
  }
  return match
    .map(m => {
      const ref = toRef(m.slice(2, m.length - 1));
      return ref == null ? null : {...ref, raw: m};
    })
    .filter(Obj.notEmpty);
}
export function parseSpecFields(spec: VisualizationSpec): FieldRef[] {
  const refs = _.uniqWith(
    _.flatMap(
      _.filter(flatten(spec), v => typeof v === 'string'),
      v => extractRefs(v)
    ),
    _.isEqual
  );
  return refs;
}
export function fieldInjectResult(
  ref: FieldRef,
  userSettings: UserSettings
): string | null {
  let result = '';
  switch (ref.type) {
    case 'field':
      result = userSettings.fieldSettings?.[ref.name] || '';
      result = result.replace(/\./g, '\\.');
      result = _.replace(result, '/', '_');
      return result;
    case 'string':
      return userSettings.stringSettings?.[ref.name] || ref.default || '';
    default:
      return null;
  }
}

export function makeInjectMap(
  refs: FieldRef[],
  userSettings: UserSettings
): Array<{from: string; to: string}> {
  const result: Array<{from: string; to: string}> = [];
  for (const ref of refs) {
    const inject = fieldInjectResult(ref, userSettings);
    if (inject != null) {
      result.push({
        from: ref.raw,
        to: inject,
      });
    }
  }
  return result;
}

export function injectFields(
  spec: VisualizationSpec,
  refs: FieldRef[],
  userSettings: UserSettings
): VisualizationSpec {
  const injectMap = makeInjectMap(refs, userSettings);
  return Obj.deepMapValuesAndArrays(spec, (s: any) => {
    if (typeof s === 'string') {
      for (const mapping of injectMap) {
        // Replace all (s.replace only replaces the first occurrence)
        s = s.split(mapping.from).join(mapping.to);
      }
    }
    return s;
  });
}

function hasInput(specBranch: any) {
  if (typeof specBranch === 'object') {
    for (const [key, val] of Object.entries(specBranch)) {
      if (key === 'input') {
        return true;
      }
      if (hasInput(val)) {
        return true;
      }
    }
  }
  return false;
}

export function specHasBindings(spec: VisualizationSpec) {
  if (spec.$schema?.includes('vega-lite')) {
    const selection = (spec as any).selection;
    return hasInput(selection);
  } else {
    const signals = (spec as any).signals;
    if (Array.isArray(signals)) {
      for (const s of signals) {
        if (s.bind != null) {
          return true;
        }
      }
    }
  }
  return false;
}
