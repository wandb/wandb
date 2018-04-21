import * as Filter from './filters';
import * as Selection from './selections';

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

describe('Selection', () => {
  it('all', () => {
    const selection = Selection.all();
    expect(Filter.filterRuns(selection, runs).length).toBe(3);
  });

  it('none', () => {
    const selection = Selection.none();
    expect(Filter.filterRuns(selection, runs).length).toBe(0);
  });

  it('select and deselect from none', () => {
    let selection = Selection.Update.select(Selection.none(), 'name2');
    // console.log('selection', JSON.stringify(selection, null, 4));
    expect(Filter.filterRuns(selection, runs).length).toBe(1);

    selection = Selection.Update.select(selection, 'name1');
    expect(Filter.filterRuns(selection, runs).length).toBe(2);

    selection = Selection.Update.deselect(selection, 'name0');
    expect(Filter.filterRuns(selection, runs).length).toBe(2);

    selection = Selection.Update.deselect(selection, 'name1');
    expect(Filter.filterRuns(selection, runs).length).toBe(1);
  });

  it('select and deselect from all', () => {
    let selection = Selection.Update.select(Selection.all(), 'name2');
    // console.log('selection', JSON.stringify(selection, null, 4));
    expect(Filter.filterRuns(selection, runs).length).toBe(3);

    selection = Selection.Update.deselect(selection, 'name0');
    expect(Filter.filterRuns(selection, runs).length).toBe(2);

    selection = Selection.Update.deselect(selection, 'name1');
    expect(Filter.filterRuns(selection, runs).length).toBe(1);

    selection = Selection.Update.select(selection, 'name1');
    expect(Filter.filterRuns(selection, runs).length).toBe(2);
  });

  it('select range from none', () => {
    const selection = Selection.Update.addBound(
      Selection.none(),
      {section: 'config', name: 'lr'},
      '<=',
      0.7
    );
    expect(Filter.filterRuns(selection, runs).length).toBe(2);
  });

  it('select range from all', () => {
    const selection = Selection.Update.addBound(
      Selection.all(),
      {section: 'config', name: 'lr'},
      '<=',
      0.7
    );
    expect(Filter.filterRuns(selection, runs).length).toBe(2);
  });

  it('bounds', () => {
    let selection = Selection.Update.addBound(
      Selection.all(),
      {section: 'config', name: 'lr'},
      '<=',
      0.7
    );
    expect(
      Selection.bounds(selection, {section: 'config', name: 'lr'})
    ).toEqual({low: null, high: 0.7});
    expect(
      Selection.bounds(selection, {section: 'config', name: 'doesnt-xist'})
    ).toEqual({low: null, high: null});
    selection = Selection.Update.addBound(
      selection,
      {section: 'config', name: 'lr'},
      '>=',
      0.3
    );
    expect(
      Selection.bounds(selection, {section: 'config', name: 'lr'})
    ).toEqual({low: 0.3, high: 0.7});

    selection = Selection.Update.addBound(
      selection,
      {section: 'config', name: 'lr'},
      '<=',
      null
    );
    expect(
      Selection.bounds(selection, {section: 'config', name: 'lr'})
    ).toEqual({low: 0.3, high: null});
  });

  it('multiple bounds', () => {
    let selection = Selection.Update.addBound(
      Selection.all(),
      {section: 'config', name: 'lr'},
      '<=',
      0.7
    );
    selection = Selection.Update.addBound(
      selection,
      {section: 'config', name: 'lr'},
      '>=',
      0.5
    );
    selection = Selection.Update.addBound(
      selection,
      {section: 'summary', name: 'Accuracy Trousers'},
      '<=',
      0.1
    );
    selection = Selection.Update.addBound(
      selection,
      {section: 'summary', name: 'Accuracy Trousers'},
      '>=',
      0
    );
    expect(
      Selection.bounds(selection, {section: 'config', name: 'lr'})
    ).toEqual({low: 0.5, high: 0.7});
    expect(
      Selection.bounds(selection, {
        section: 'summary',
        name: 'Accuracy Trousers',
      })
    ).toEqual({low: 0, high: 0.1});
  });
});
