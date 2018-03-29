import {filterRuns, GroupFilter, IndividualFilter} from './filters';
import {Run, runKey} from './runs';

let runs: Run[];

beforeAll(() => {
  runs = [
    new Run(
      'id-shawn',
      'name0',
      'running',
      {username: 'shawn', photoUrl: 'aphoto.com'},
      'angry.local',
      new Date(2018, 2, 22),
      new Date(2018, 2, 22, 1),
      ['good', 'baseline'],
      'shawn-run\nSome interesting info',
      {lr: 0.9, momentum: 0.95},
      {acc: 0.72, loss: 0.12},
    ),
    new Run(
      'id-brian',
      'name1',
      'running',
      {username: 'brian', photoUrl: 'bphoto.com'},
      'brian.local',
      new Date(2018, 2, 23),
      new Date(2018, 2, 23, 1),
      [],
      'fancy',
      {lr: 0.6, momentum: 0.95},
      {acc: 0.8, loss: 0.05},
    ),
    new Run(
      'id-lindsay',
      'name2',
      'failed',
      {username: 'lindsay', photoUrl: 'lphoto.com'},
      'linsday.local',
      new Date(2018, 2, 24),
      new Date(2018, 2, 24, 1),
      ['hidden'],
      'testrun\nJust testing some stuff',
      {lr: 0.7, momentum: 0.94, testparam: 'yes'},
      {acc: 0.85},
    ),
  ];
});

describe('Individual Filter', () => {
  it('name =', () => {
    const filter = new IndividualFilter(
      runKey('run', 'name'),
      '=',
      'shawn-run',
    );
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
  });

  it('state !=', () => {
    const filter = new IndividualFilter(runKey('run', 'state'), '!=', 'failed');
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });

  it('config >=', () => {
    const filter = new IndividualFilter(runKey('config', 'lr'), '>=', 0.7);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-brian'});
    expect(result[1]).toMatchObject({id: 'id-lindsay'});
  });

  it('config <=', () => {
    const filter = new IndividualFilter(runKey('config', 'lr'), '<=', 0.7);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-lindsay'});
  });

  it('summary <', () => {
    const filter = new IndividualFilter(runKey('summary', 'loss'), '<', 0.1);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
  });

  it('summary >', () => {
    const filter = new IndividualFilter(runKey('summary', 'loss'), '>', 0.1);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-brian'});
  });
});

describe('Group Filter', () => {
  it('AND', () => {
    const filter = new GroupFilter('AND', [
      new IndividualFilter(runKey('run', 'state'), '=', 'running'),
      new IndividualFilter(runKey('run', 'host'), '=', 'brian.local'),
    ]);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({id: 'id-brian'});
  });

  it('OR', () => {
    const filter = new GroupFilter('OR', [
      new IndividualFilter(runKey('run', 'host'), '=', 'angry.local'),
      new IndividualFilter(runKey('run', 'host'), '=', 'brian.local'),
    ]);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });

  it('OR of AND', () => {
    const filter = new GroupFilter('OR', [
      new IndividualFilter(runKey('run', 'host'), '=', 'angry.local'),
      new GroupFilter('AND', [
        new IndividualFilter(runKey('run', 'state'), '=', 'running'),
        new IndividualFilter(runKey('run', 'host'), '=', 'brian.local'),
      ]),
    ]);
    const result = filterRuns(filter, runs);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({id: 'id-shawn'});
    expect(result[1]).toMatchObject({id: 'id-brian'});
  });
});
