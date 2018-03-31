import {flatten} from 'flat';
import * as _ from 'lodash';
import {JSONparseNaN} from './jsonnan';
import * as Parse from './parse';

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

export type Value = string | number | boolean | null;

// config and summary are stored as KeyVal
interface KeyVal {
  readonly [key: string]: Value;
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
  readonly createdAt: Date;
  readonly heartbeatAt: Date;
  readonly tags: string[];
  readonly description: string;
  readonly config: KeyVal;
  readonly summary: KeyVal;
}

export function fromJson(json: any): Run | null {
  // Safely parse a json object as returned from the server into a validly typed Run
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

  const state = json.state;
  if (typeof name !== 'string' || name.length === 0) {
    console.warn(`Invalid run state: ${json.state}`);
    return null;
  }

  const user = json.user;
  if (user == null || user.username == null || user.photoUrl == null) {
    console.warn(`Invalid user for run ${name}:`, json.user);
    return null;
  }

  const host = json.host;
  if (typeof host !== 'string') {
    console.warn(`Invalid run host: ${json.host}`);
    return null;
  }

  const createdAt = Parse.parseDate(json.createdAt);
  if (createdAt == null) {
    console.warn(`Invalid createdAt for run ${name}:`, json.createdAt);
    return null;
  }

  const heartbeatAt = Parse.parseDate(json.heartbeatAt);
  if (heartbeatAt == null) {
    console.warn(`Invalid heartbeatAt for run ${name}:`, json.heartbeatAt);
    return null;
  }

  const tags = json.tags;
  if (
    !(tags instanceof Array) ||
    !tags.every((tag: any) => typeof tag === 'string')
  ) {
    console.warn(`Invalid tags for run ${name}:`, json.tags);
    return null;
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
    createdAt,
    heartbeatAt,
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
    flatten(_.mapValues(config, extractConfigValue)),
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
      ),
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
    if (name === 'id') {
      // Alias 'id' to 'name'.
      return run.name;
    } else if (name === 'name') {
      return displayName(run);
    } else if (name === 'userName') {
      return run.user.username;
    } else if (name === 'state') {
      return run.state;
    } else if (name === 'host') {
      return run.host;
    } else {
      return null;
    }
  } else if (section === 'tags') {
    return _.indexOf(run.tags, name) !== -1;
  } else if (section === 'config') {
    return run.config[name];
  } else if (section === 'summary') {
    return run.summary[name];
  }
  return null;
}
