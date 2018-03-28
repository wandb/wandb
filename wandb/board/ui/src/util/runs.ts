import {flatten} from 'flat';
import * as _ from 'lodash';
import {JSONparseNaN} from './jsonnan';
import * as Parse from './parse';

interface RunKey {
  section: string;
  name: string;
}

// Matches JSON types
type RunValue = string | number | boolean | null;

// config and summary are stored as KeyVal
interface KeyVal {
  readonly [key: string]: RunValue;
}

interface User {
  username: string;
  photoUrl: string;
}

export class Run {
  // Holds summary data from a single run, as returned by the ModelRuns query.
  static fromJson(json: any): Run | null {
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

    const config = Run.parseConfig(json.config, name);
    if (config == null) {
      return null;
    }

    const summary = Run.parseSummary(json.summaryMetrics, name);
    if (summary == null) {
      return null;
    }

    return new Run(
      id,
      name,
      state,
      user,
      host,
      createdAt,
      heartbeatAt,
      tags,
      typeof json.description === 'string' ? json.description : '',
      config,
      summary,
    );
  }

  private static extractConfigValue(confVal: any) {
    // Config values are supposed to be of the shape {value: <value>, desc: <description>}
    if (confVal == null || confVal.value == null) {
      return null;
    }
    return confVal.value;
  }

  private static parseConfig(confJson: any, runName: string): KeyVal | null {
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
    config = flatten(_.mapValues(config, Run.extractConfigValue));
    return config;
  }

  private static parseSummary(
    confSummary: any,
    runName: string,
  ): KeyVal | null {
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
    return summary;
  }

  constructor(
    public readonly id: string,
    public readonly name: string,
    public readonly state: string,
    public readonly user: User,
    public readonly host: string,
    public readonly createdAt: Date,
    public readonly heartbeatAt: Date,
    public readonly tags: string[],
    public readonly description: string,
    public readonly config: KeyVal,
    public readonly summary: KeyVal,
  ) {}

  displayName() {
    if (this.description.length > 0) {
      return this.description.split('\n')[0];
    }
    return this.name || '';
  }

  getValue(key: RunKey): RunValue {
    const {section, name} = key;
    if (section === 'run') {
      if (name === 'id') {
        // Alias 'id' to 'name'.
        return this.name;
      } else if (name === 'name') {
        return this.displayName();
      } else if (name === 'userName') {
        return this.user.username;
      } else {
        return null;
      }
    } else if (section === 'tags') {
      return _.indexOf(this.tags, name) !== -1;
    } else if (section === 'config') {
      return this.config[name];
    } else if (section === 'summary') {
      return this.summary[name];
    }
    return null;
  }
}
