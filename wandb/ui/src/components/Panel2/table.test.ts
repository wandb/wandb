import * as Table from './table';

const PREDS_TABLE = {
  columns: ['image', 'dominant_class', 'score_cat', 'score_dog'],
  data: [
    [
      {
        _type: 'image-file',
        width: 200,
        height: 180,
        path: 'media/images/img-1xah15.png',
        size: 14186,
        boxes: {
          ground_truth: [
            {
              position: {
                minX: 0.1,
                maxX: 0.2,
                minY: 0.3,
                maxY: 0.4,
              },
              class_id: 4,
              scores: {
                acc: 0.94,
              },
            },
          ],
        },
      },
      'cat',
      0.88,
      0.23,
    ],
    [
      {
        _type: 'image-file',
        width: 220,
        height: 190,
        path: 'media/images/img-9xah22.png',
        size: 13816,
        boxes: {
          ground_truth: [
            {
              position: {
                minX: 0.2,
                maxX: 0.2,
                minY: 0.3,
                maxY: 0.4,
              },
              class_id: 3,
              scores: {
                acc: 0.12,
              },
            },
          ],
        },
      },
      'dog',
      0.19,
      0.23,
    ],
    [
      {
        _type: 'image-file',
        width: 220,
        height: 190,
        path: 'media/images/img-fxjh12.png',
        size: 13129,
        boxes: {
          ground_truth: [
            {
              position: {
                minX: 0.1,
                maxX: 0.2,
                minY: 0.3,
                maxY: 0.4,
              },
              class_id: 3,
              scores: {
                acc: 0.14,
              },
            },
          ],
        },
      },
      'dog',
      0.12,
      0.29,
    ],
  ],
};

const PREDS_TABLE_METADATA = {
  alias: 'table1',
  table: {
    path: {
      entityName: 'shawn',
      projectName: 'projo',
      artifactTypeName: 'dataset',
      artifactSequenceName: 'animals',
      artifactCommitHash: 'v1',
      path: 'animals-table',
    },
    columns: [
      {name: 'image', type: 'image-file' as const},
      {name: 'dominant_class', type: 'string' as const},
    ],
  },
};

const PREDS_TABLE2 = {...PREDS_TABLE, data: PREDS_TABLE.data.slice(0, 1)};
const PREDS_TABLE_METADATA2 = {...PREDS_TABLE_METADATA, alias: 'table2'};

describe('doTableQuery', () => {
  it('basic select', () => {
    const result = Table.doTableQuery(
      {
        select: [
          {
            tableAlias: 'table1',
            tableColumn: 'dominant_class',
            name: 'domcls',
          },
          {
            tableAlias: 'table1',
            tableColumn: 'score_cat',
            name: 'scorecat',
          },
        ],
        from: {
          tables: [PREDS_TABLE_METADATA],
          joinKeys: [{column: 'image', jsonPath: ['path']}],
        },
      },
      [PREDS_TABLE]
    );
    expect(result).toEqual([
      ['cat', 0.88],
      ['dog', 0.19],
      ['dog', 0.12],
    ]);
  });

  it('basic sort', () => {
    const result = Table.doTableQuery(
      {
        select: [
          {
            tableAlias: 'table1',
            tableColumn: 'dominant_class',
            name: 'domcls',
          },
          {
            tableAlias: 'table1',
            tableColumn: 'score_cat',
            name: 'scorecat',
          },
        ],
        sort: [{key: 'table1.score_cat', ascending: true}],
        from: {
          tables: [PREDS_TABLE_METADATA],
          joinKeys: [{column: 'image', jsonPath: ['path']}],
        },
      },
      [PREDS_TABLE]
    );
    expect(result).toEqual([
      ['dog', 0.12],
      ['dog', 0.19],
      ['cat', 0.88],
    ]);
  });

  it('grouped', () => {
    const result = Table.doTableQuery(
      {
        select: [
          {
            tableAlias: 'table1',
            tableColumn: 'dominant_class',
            name: 'domcls',
          },
          {
            tableAlias: 'table1',
            tableColumn: 'score_cat',
            name: 'scorecat',
          },
        ],
        groupBy: ['table1.dominant_class'],
        from: {
          tables: [PREDS_TABLE_METADATA],
          joinKeys: [{column: 'image', jsonPath: ['path']}],
        },
      },
      [PREDS_TABLE]
    );
    expect(result).toEqual([
      ['cat', [0.88]],
      ['dog', [0.19, 0.12]],
    ]);
  });

  it('joined', () => {
    const result = Table.doTableQuery(
      {
        select: [
          {
            tableAlias: 'table1',
            tableColumn: 'dominant_class',
            name: 'domcls',
          },
          {
            tableAlias: 'table2',
            tableColumn: 'score_cat',
            name: 'scorecat',
          },
        ],
        from: {
          tables: [PREDS_TABLE_METADATA, PREDS_TABLE_METADATA2],
          joinKeys: [
            {column: 'image', jsonPath: ['path']},
            {column: 'image', jsonPath: ['path']},
          ],
        },
      },
      [PREDS_TABLE, PREDS_TABLE2]
    );
    expect(result).toEqual([
      ['cat', 0.88],
      ['dog', null],
      ['dog', null],
    ]);
  });
});
