import update from 'immutability-helper';
import * as Filter from './filters';
import * as Run from './runs';

const runs = [
  {
    id: 'id-shawn',
    name: 'name0',
    state: 'running',
    user: {username: 'shawn', photoUrl: 'aphoto.com'},
    host: 'angry.local',
    createdAt: new Date(2018, 2, 22).toISOString(),
    heartbeatAt: new Date(2018, 2, 22, 1).toISOString(),
    tags: ['good', 'baseline'],
    description: 'shawn-run\nSome interesting info',
    config: {lr: 0.9, momentum: 0.95},
    summary: {acc: 0.72, loss: 0.12},
  },
  {
    id: 'id-brian',
    name: 'name1',
    state: 'running',
    user: {username: 'brian', photoUrl: 'bphoto.com'},
    host: 'brian.local',
    createdAt: new Date(2018, 2, 23).toISOString(),
    heartbeatAt: new Date(2018, 2, 23, 1).toISOString(),
    tags: [],
    description: 'fancy',
    config: {lr: 0.6, momentum: 0.95},
    summary: {acc: 0.8, loss: 0.05},
  },
  {
    id: 'id-lindsay',
    name: 'name2',
    state: 'failed',
    user: {username: 'lindsay', photoUrl: 'lphoto.com'},
    host: 'linsday.local',
    createdAt: new Date(2018, 2, 24).toISOString(),
    heartbeatAt: new Date(2018, 2, 24, 1).toISOString(),
    tags: ['hidden'],
    description: 'testrun\nJust testing some stuff',
    config: {lr: 0.7, momentum: 0.94, testparam: 'yes'},
    summary: {acc: 0.85},
  },
];

const goodFilters: Filter.Filter = {
  op: 'OR',
  filters: [
    {key: Run.key('run', 'host')!, op: '=', value: 'angry.local'},
    {
      op: 'AND',
      filters: [
        {key: Run.key('run', 'state')!, op: '=', value: 'running'},
        {key: Run.key('run', 'host')!, op: '=', value: 'brian.local'},
      ],
    },
  ],
};

describe('Individual Filter', () => {
  it('name =', () => {
    const filter: Filter.Filter = {
      key: Run.key('run', 'name')!,
      op: '=',
      value: 'shawn-run',
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
  });

  it('state !=', () => {
    const filter: Filter.Filter = {
      key: Run.key('run', 'state')!,
      op: '!=',
      value: 'failed',
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });

  it('config <=', () => {
    const filter: Filter.Filter = {
      key: Run.key('config', 'lr')!,
      op: '<=',
      value: 0.7,
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-brian'});
    expect(result[1]).toMatchObject({id: 'id-lindsay'});
  });

  it('config >=', () => {
    const filter: Filter.Filter = {
      key: Run.key('config', 'lr')!,
      op: '>=',
      value: 0.7,
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-lindsay'});
  });

  it('summary >', () => {
    const filter: Filter.Filter = {
      key: Run.key('summary', 'loss')!,
      op: '>',
      value: 0.1,
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
  });

  it('summary <', () => {
    const filter: Filter.Filter = {
      key: Run.key('summary', 'loss')!,
      op: '<',
      value: 0.1,
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-brian'});
  });
});

describe('Group Filter', () => {
  it('AND', () => {
    const filter: Filter.Filter = {
      op: 'AND',
      filters: [
        {key: Run.key('run', 'state')!, op: '=', value: 'running'},
        {key: Run.key('run', 'host')!, op: '=', value: 'brian.local'},
      ],
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-brian'});
  });

  it('OR', () => {
    const filter: Filter.Filter = {
      op: 'OR',
      filters: [
        {key: Run.key('run', 'host')!, op: '=', value: 'angry.local'},
        {key: Run.key('run', 'host')!, op: '=', value: 'brian.local'},
      ],
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });

  it('OR of AND', () => {
    const filter: Filter.Filter = {
      op: 'OR',
      filters: [
        {key: Run.key('run', 'host')!, op: '=', value: 'angry.local'},
        {
          op: 'AND',
          filters: [
            {key: Run.key('run', 'state')!, op: '=', value: 'running'},
            {key: Run.key('run', 'host')!, op: '=', value: 'brian.local'},
          ],
        },
      ],
    };
    const result = Filter.filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });
});

describe('fromJson', () => {
  it('good filters', () => {
    expect(Filter.fromJson(goodFilters)).toEqual(goodFilters);
  });

  it('string-keyed filter', () => {
    expect(Filter.fromJson({key: 'config:lr', op: '>=', value: 0.9})).toEqual({
      key: Run.key('config', 'lr'),
      op: '>=',
      value: 0.9,
    });
  });

  it('bad filter op', () => {
    expect(
      Filter.fromJson({
        op: 'And',
        filters: [],
      }),
    ).toBe(null);
  });

  it('bad filter key', () => {
    expect(
      Filter.fromJson({
        key: {section: 'none'},
        op: '=',
        value: 14,
      }),
    ).toBe(null);
  });
});

describe('fromOldURL', () => {
  it('good', () => {
    expect(
      Filter.fromOldURL([
        JSON.stringify(['run:host', '=', 'shawn.local']),
        JSON.stringify(['tags:hidden', '=', 'false']),
      ]),
    ).toEqual({
      op: 'OR',
      filters: [
        {
          op: 'AND',
          filters: [
            {
              key: {section: 'run', name: 'host'},
              op: '=',
              value: 'shawn.local',
            },
            {
              key: {section: 'tags', name: 'hidden'},
              op: '=',
              value: false,
            },
          ],
        },
      ],
    });
  });

  it('bad', () => {
    expect(Filter.fromOldURL(['run:host=shawn.local'])).toBe(null);
  });
});

describe('to and fromURL', () => {
  it('good', () => {
    expect(Filter.fromURL(Filter.toURL(goodFilters))).toEqual(goodFilters);
  });
});

describe('filter modifiers', () => {
  it('groupPush works', () => {
    const result = Filter.Update.groupPush(goodFilters, ['1'], {
      key: {section: 'run', name: 'host'},
      op: '=',
      value: 'brian.local',
    });
    expect(result).toEqual({
      filters: [
        {key: {name: 'host', section: 'run'}, op: '=', value: 'angry.local'},
        {
          filters: [
            {key: {name: 'state', section: 'run'}, op: '=', value: 'running'},
            {
              key: {name: 'host', section: 'run'},
              op: '=',
              value: 'brian.local',
            },
            {
              key: {name: 'host', section: 'run'},
              op: '=',
              value: 'brian.local',
            },
          ],
          op: 'AND',
        },
      ],
      op: 'OR',
    });
  });

  it('groupRemove works', () => {
    const result = Filter.Update.groupRemove(goodFilters, ['1'], 1);
    expect(result).toEqual({
      filters: [
        {key: {name: 'host', section: 'run'}, op: '=', value: 'angry.local'},
        {
          filters: [
            {key: {name: 'state', section: 'run'}, op: '=', value: 'running'},
          ],
          op: 'AND',
        },
      ],
      op: 'OR',
    });
  });

  it('groupRemove top-level works', () => {
    const result = Filter.Update.groupRemove(goodFilters, [], 1);
    expect(result).toEqual({
      filters: [
        {key: {name: 'host', section: 'run'}, op: '=', value: 'angry.local'},
      ],
      op: 'OR',
    });
  });

  it('setKey works', () => {
    const result = Filter.Update.setFilter(goodFilters, ['1', '0'], {
      key: {
        section: 'config',
        name: 'lr',
      },
      op: '>=',
      value: 0.9,
    });
    expect(result).toEqual({
      filters: [
        {key: {name: 'host', section: 'run'}, op: '=', value: 'angry.local'},
        {
          filters: [
            {key: {name: 'lr', section: 'config'}, op: '>=', value: 0.9},
            {
              key: {name: 'host', section: 'run'},
              op: '=',
              value: 'brian.local',
            },
          ],
          op: 'AND',
        },
      ],
      op: 'OR',
    });
  });

  it('countIndividual works', () => {
    expect(Filter.countIndividual(goodFilters)).toBe(3);
  });
});
