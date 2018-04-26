import {flatten} from 'flat';
import * as _ from 'lodash';
import * as numeral from 'numeral';
import {JSONparseNaN} from './jsonnan';
import * as Parse from './parse';
import * as String from './string';

// These two must match
const runKeySections = ['run', 'tags', 'config', 'summary'];
type RunKeySection = 'run' | 'tags' | 'config' | 'summary';
// TODO: Is there a way to constrain name when section is run?
export interface Key {
  section: RunKeySection;
  name: string;
}

export function key(section: string, name: string): Key | null {
  if (_.indexOf(runKeySections, section) === -1) {
    return null;
  }
  return {section: section as RunKeySection, name};
}

export function keyFromString(keyString: string): Key | null {
  let [section, name] = keyString.split(':', 2);
  if (name == null) {
    name = section;
    section = 'run';
  }
  return key(section, name);
}

export function keyToString(k: Key): string {
  return k.section + ':' + k.name;
}

export type Value = string | number | boolean | null;

export type DomValue = string | number;

// config and summary are stored as KeyVal
interface KeyVal {
  // The compiler doesn't like when we an array of runs that have different config keys (in tests),
  // unless we allow undefined here.
  readonly [key: string]: Value | undefined;
}

interface User {
  username: string;
  photoUrl: string;
}

export interface Run {
  readonly id: string;
  readonly name: string;
  readonly state: string; // TODO: narrow this type
  readonly user: User;
  readonly host: string;
  readonly createdAt: string;
  readonly heartbeatAt: string;
  readonly tags: string[];
  readonly description: string;
  readonly config: KeyVal;
  readonly summary: KeyVal;
}

export function fromJson(json: any): Run | null {
  // Safely parse a json object as returned from the server into a validly typed Run
  // This used to return null in a lot more cases, now if we receive invalid data we
  // set the values to defaults. This happens when we select specific fields from
  // the run in the graphql query (for Scatter and Parallel Coordinates plots). It'd
  // probably be better to have a special type for those cases, instead of using default
  // values, so that other parts of the code has better guarantees about what to expect.
  if (typeof json !== 'object') {
    return null;
  }
  const id = json.id;
  if (typeof id !== 'string' || id.length === 0) {
    console.warn(`Invalid run id: ${json.id}`);
    return null;
  }

  const name = json.name;
  if (typeof name !== 'string' || name.length === 0) {
    console.warn(`Invalid run name: ${json.name}`);
    return null;
  }

  let state = json.state;
  if (typeof name !== 'string' || name.length === 0) {
    state = 'unknown';
  }

  let user = json.user;
  if (user == null || user.username == null || user.photoUrl == null) {
    user = {
      name: '',
      photoUrl: '',
    };
  }

  let host = json.host;
  if (typeof host !== 'string' && host !== null) {
    host = '';
  }

  let createdAt = Parse.parseDate(json.createdAt);
  if (createdAt == null) {
    createdAt = new Date();
  }

  let heartbeatAt = Parse.parseDate(json.heartbeatAt);
  if (heartbeatAt == null) {
    heartbeatAt = new Date();
  }

  let tags = json.tags;
  if (
    !(tags instanceof Array) ||
    !tags.every((tag: any) => typeof tag === 'string')
  ) {
    tags = [];
  }

  const config = parseConfig(json.config, name);
  if (config == null) {
    return null;
  }

  const summary = parseSummary(json.summaryMetrics, name);
  if (summary == null) {
    return null;
  }

  return {
    id,
    name,
    state,
    user,
    host,
    createdAt: createdAt.toISOString(),
    heartbeatAt: heartbeatAt.toISOString(),
    tags,
    description: typeof json.description === 'string' ? json.description : '',
    config,
    summary,
  };
}

function extractConfigValue(confVal: any) {
  // Config values are supposed to be of the shape {value: <value>, desc: <description>}
  if (confVal == null || confVal.value == null) {
    return null;
  }
  return confVal.value;
}

function parseConfig(confJson: any, runName: string): KeyVal | null {
  let config: any;
  try {
    config = JSONparseNaN(confJson);
  } catch {
    console.warn(`Couldn\'t parse config for run ${runName}:`, confJson);
    return null;
  }
  if (typeof config !== 'object') {
    console.warn(`Invalid config for run ${runName}:`, confJson);
    return null;
  }
  config = removeEmptyListsAndObjects(
    flatten(_.mapValues(config, extractConfigValue))
  );
  return config;
}

function parseSummary(confSummary: any, runName: string): KeyVal | null {
  let summary: any;
  try {
    summary = JSONparseNaN(confSummary);
  } catch {
    console.warn(`Couldn\'t parse summary for run ${runName}:`, confSummary);
    return null;
  }
  if (typeof summary !== 'object') {
    console.warn(`Invalid summary for run ${runName}:`, confSummary);
    return null;
  }
  summary = removeEmptyListsAndObjects(flatten(summary));
  return summary;
}

function removeEmptyListsAndObjects(obj: any) {
  // Flatten will return [] or {} as values. We keys with those values
  // to simplify typing and behavior everywhere else.
  return _.pickBy(
    obj,
    o =>
      !(
        (_.isArray(o) && o.length === 0) ||
        (_.isObject(o) && _.keys(o).length === 0)
      )
  );
}

export function displayName(run: Run) {
  if (run.description.length > 0) {
    return run.description.split('\n')[0];
  }
  return run.name || '';
}

export function getValue(run: Run, runKey: Key): Value {
  const {section, name} = runKey;
  if (section === 'run') {
    if (name === 'name') {
      return run.name;
    } else if (name === 'displayName') {
      return displayName(run);
    } else if (name === 'userName') {
      return run.user.username;
    } else if (name === 'state') {
      return run.state;
    } else if (name === 'host') {
      return run.host;
    } else if (name === 'createdAt') {
      return run.createdAt;
    } else {
      return null;
    }
  } else if (section === 'tags') {
    return _.indexOf(run.tags, name) !== -1;
  } else if (section === 'config') {
    return run.config[name] || null;
  } else if (section === 'summary') {
    return run.summary[name] || null;
  }
  return null;
}

export function sortableValue(value: Value) {
  if (typeof value === 'number' || typeof value === 'string') {
    return value;
  } else {
    return JSON.stringify(value);
  }
}

export function valueString(value: Value) {
  if (value == null) {
    return 'null';
  }
  return value.toString();
}

export function displayKey(k: Key) {
  if (k.section && k.name !== '') {
    if (k.section === 'run') {
      return k.name;
    } else {
      return k.section + ':' + k.name;
    }
  } else {
    return '-';
  }
}

export function displayValue(value: Value) {
  if (value == null) {
    return '-';
  } else if (typeof value === 'number' && _.isFinite(value)) {
    return numeral(value).format('0.[000]');
  }
  return value.toString();
}

export function domValue(value: Value): DomValue {
  if (typeof value === 'number' || typeof value === 'string') {
    return value;
  }
  if (typeof value === 'boolean') {
    return value.toString();
  }
  return 'null';
}

export function parseValue(val: any): Value {
  let parsedValue: Value = null;
  if (typeof val === 'number' || typeof val === 'boolean') {
    parsedValue = val;
  } else if (typeof val === 'string') {
    parsedValue = parseFloat(val);
    if (!isNaN(parsedValue)) {
      // If value is '3.' we just get 3, but we return the string '3.' so this can be used in input
      // fields.
      if (parsedValue.toString().length !== val.length) {
        parsedValue = val;
      }
    } else {
      if (val.indexOf('.') === -1) {
        if (val === 'true') {
          parsedValue = true;
        } else if (val === 'false') {
          parsedValue = false;
        } else if (val === 'null') {
          parsedValue = null;
        } else if (typeof val === 'string') {
          parsedValue = val;
        }
      } else {
        parsedValue = val;
      }
    }
  }
  return parsedValue;
}

export function serverPathToKey(pathString: string): Key | null {
  const [section, name] = String.splitOnce(pathString, '.');
  if (name == null) {
    return null;
  }
  if (section === 'config') {
    if (!_.endsWith(name, '.value')) {
      return null;
    }
    return {
      section: 'config',
      name: name.slice(0, name.length - 6),
    };
  } else if (section === 'summary_metrics') {
    return {
      section: 'summary',
      name,
    };
  }
  return null;
}

export function serverPathToKeyString(pathString: string): string | null {
  const k = serverPathToKey(pathString);
  if (k == null) {
    return null;
  }
  return keyToString(k);
}

export function keyToServerPath(k: Key): string | null {
  if (k.section === 'config') {
    return 'config.' + k.name + '.value';
  } else if (k.section === 'summary') {
    return 'summary_metrics.' + k.name;
  } else if (k.section === 'run') {
    return k.name;
  } else if (k.section === 'tags') {
    return 'tags.' + k.name;
  } else {
    return null;
  }
}

export function keyStringToServerPath(keyString: string): string | null {
  const k = keyFromString(keyString);
  if (k == null) {
    return null;
  }
  return keyToServerPath(k);
}
