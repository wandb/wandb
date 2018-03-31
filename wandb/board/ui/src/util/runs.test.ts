import * as Run from './runs';

const CREATED_AT = '2018-03-28T02:19:09.777';
const VALID_RUN_JSON = {
  id: 'my_run_id',
  name: 'arun',
  state: 'running',
  user: {username: 'mcgee', photoUrl: 'example.com'},
  host: 'angry.local',
  createdAt: CREATED_AT,
  heartbeatAt: CREATED_AT,
  tags: ['a', 'b'],
  config: '{"akey": {"value": {"subkey": 14}}, "bkey": 19.3}',
  summaryMetrics: '{"acc": 0.14}',
};

describe('Runs Factory', () => {
  it('works with valid run', () => {
    const result = Run.fromJson(VALID_RUN_JSON);
    expect(result).toEqual({
      id: 'my_run_id',
      name: 'arun',
      state: 'running',
      description: '',
      user: {username: 'mcgee', photoUrl: 'example.com'},
      host: 'angry.local',
      createdAt: new Date(CREATED_AT + 'z'),
      heartbeatAt: new Date(CREATED_AT + 'z'),
      tags: ['a', 'b'],
      config: {'akey.subkey': 14, bkey: null},
      summary: {acc: 0.14},
    });
  });

  it('fails without name', () => {
    const run = {...VALID_RUN_JSON};
    delete run.name;
    expect(Run.fromJson(run)).toBe(null);
  });

  it('fails with non-string name', () => {
    const run = {...VALID_RUN_JSON, name: 5};
    expect(Run.fromJson(run)).toBe(null);
  });

  it('fails without user', () => {
    const run = {...VALID_RUN_JSON};
    delete run.user;
    expect(Run.fromJson(run)).toBe(null);
  });

  it('fails with invalid user', () => {
    const run = {...VALID_RUN_JSON, user: []};
    expect(Run.fromJson(run)).toBe(null);
  });

  it('fails without tags', () => {
    const run = {...VALID_RUN_JSON};
    delete run.tags;
    expect(Run.fromJson(run)).toBe(null);
  });

  it('fails with invalid tags', () => {
    const run1 = {...VALID_RUN_JSON, tags: {a: 5}};
    expect(Run.fromJson(run1)).toBe(null);
    const run2 = {...VALID_RUN_JSON, tags: [5]};
    expect(Run.fromJson(run2)).toBe(null);
  });
});

describe('Run', () => {
  it('displayName works', () => {
    const run = Run.fromJson(VALID_RUN_JSON);
    expect(run).not.toBe(null);
    expect(Run.displayName(run!)).toBe('arun');
  });

  it('getValue works', () => {
    const run = Run.fromJson(VALID_RUN_JSON);
    expect(run).not.toBe(null);
    const name = Run.getValue(run!, {section: 'run', name: 'name'});
    expect(name).toBe('arun');
    const configValue = Run.getValue(run!, {
      section: 'config',
      name: 'akey.subkey',
    });
    expect(configValue).toBe(14);
  });
});
