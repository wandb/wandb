import * as _ from 'lodash';
import {useMemo} from 'react';
import * as File from './files';
import * as MediaTable from './mediaTable';
import {useDeepMemo} from './hooks';
import mingo from 'mingo';
import {OperatorType, useOperators as mingoUseOperators} from 'mingo/core';
import {$match} from 'mingo/operators/pipeline';
import {$size, $filter} from 'mingo/operators/expression';
import {useFileContent} from './files';
import * as Obj from '../../util/obj';
import * as Types from './types';

// ensure the required operators are preloaded prior to using them.
mingoUseOperators(OperatorType.EXPRESSION, {$size, $filter});
mingoUseOperators(OperatorType.PIPELINE, {$match});

export const SUPPORTED_MONGO_AGG_OPS = [
  '$eq',
  '$ne',
  '$gt',
  '$gte',
  '$lt',
  '$lte',
  '$filter',
  '$size',
  '$and',
  '$or',
];

export interface TableColumnMetadata {
  columns: Array<{
    name: string;
    type: MediaTable.MediaType;
  }>;
}

type TableMetadata = {
  path: File.FullFilePath;
} & TableColumnMetadata;

export interface SelectCol {
  tableAlias: string;
  tableColumn: string;
  name: string;
}

export interface JoinKey {
  column: string;
  jsonPath?: string[];
}

interface JoinQuery {
  select: SelectCol[];
  // TODO: This doesn't support full sql style joins
  from: From;
}

export interface From {
  tables: Array<{alias: string; table: TableMetadata}>;
  joinKeys: JoinKey[];
}

export interface Comparison {
  col: string;
  op: '=' | '!=';
  val: any;
}
export interface Pred {
  comb: 'and' | 'or';
  subs: Comparison[];
}

export interface MongoFilter {
  [key: string]: any;
}

export const EMPTY_MONGO_FILTER: MongoFilter = {};

function walk(obj: any, fn: (o: any) => void): void {
  if (Array.isArray(obj)) {
    for (const o of obj) {
      walk(o, fn);
    }
  } else if (_.isPlainObject(obj)) {
    fn(obj);
    for (const v of Object.values(obj)) {
      walk(v, fn);
    }
  }
}

export function assertMongoFilterIsSupported(filter: MongoFilter): void {
  walk(filter, o => {
    for (const k of Object.keys(o)) {
      if (k.startsWith('$') && !_.includes(SUPPORTED_MONGO_AGG_OPS, k)) {
        throw new Error(`unsupported mongo operator found: ${k}`);
      }
    }
  });
}

export function filterWithMongo<T extends object>(
  collection: T[],
  filter: MongoFilter
): T[] {
  const pipeline = [{$match: {$expr: filter}}];
  return mingo.aggregate(collection, pipeline);
}

export const EXAMPLE_FILTER = `{
  $gte: [
    {
      $size: {
        $filter: {
          input: '$0.example3.boxes.ground_truth.box_data',
          as: 'box',
          cond: {
            $eq: ['$$box.class_id', 1]
          }
        }
      }
    },
    4
  ]
}`;

// TODO support equations
interface SortField {
  key: string;
  ascending: boolean;
}

export type Sort = SortField[];

export type GroupBy = string[];

export type TableQuery = JoinQuery & {
  where?: Pred;
  groupBy?: GroupBy;
  sort?: Sort;
  filter?: MongoFilter;
  offset?: number;
  limit?: number;
};

export function isJoinQuery(t: TableQuery): t is JoinQuery {
  return (t as JoinQuery).from.tables != null;
}

function joinTables(
  tables: {[alias: string]: MediaTable.MediaTable},
  joinKeys: {[alias: string]: JoinKey}
) {
  const colIds = _.fromPairs(
    _.map(tables, (t, alias) => [
      alias,
      _.fromPairs(t.columns.map((c, i) => [c, i])),
    ])
  );
  const indexes = _.fromPairs(
    _.map(tables, (t, alias) => [
      alias,
      _.fromPairs(
        t.data.map(row => {
          const joinKey = joinKeys[alias];
          const colIndex = colIds[alias][joinKey.column];
          // TODO: colIndex could be null
          let val = row[colIndex];
          if (joinKey.jsonPath) {
            val = _.get(val, joinKey.jsonPath);
          }
          return [val, _.mapValues(colIds[alias], i => row[i])];
        })
      ),
    ])
  );
  const allKeys = _.union(..._.values(indexes).map(index => _.keys(index)));
  const allTableAliases = Object.keys(tables);
  const result: Array<{[tableAlias: string]: {[colName: string]: any}}> = [];
  for (const key of allKeys) {
    result.push(_.fromPairs(allTableAliases.map(ta => [ta, indexes[ta][key]])));
  }
  return result;
}

export type ResultTable = MediaTable.MediaTable & {
  context: File.FullFilePath[];
};

const DEFAULT_SORT = [{key: '_index', ascending: true}];

export const getSort = (sort: Sort | undefined): Sort => {
  if (sort == null || sort.length === 0) {
    return DEFAULT_SORT;
  }
  return sort;
};

export const useTableQuery = (
  query: TableQuery,
  options?: {skip?: boolean}
) => {
  query = useDeepMemo(query);
  options = useDeepMemo(options);
  const tables = query.from.tables.map(t => t.table);
  const contents = useFileContent(
    tables.map(t => t.path),
    {skip: options?.skip}
  );
  const loading = contents.filter(f => f.loading).length > 0;
  const table = useMemo(() => {
    if (options?.skip || loading) {
      return {
        columns: [],
        context: [],
        data: [],
      };
    }
    const parsed = contents.map(c => {
      if (c.contents == null) {
        throw new Error('invalid');
      }
      try {
        return JSON.parse(c.contents) as MediaTable.MediaTable;
      } catch {
        // TODO
        throw new Error('invalid');
      }
    });

    const result = doTableQuery(query, parsed);
    const fromByAlias = _.fromPairs(
      query.from.tables.map(t => [t.alias, t.table])
    );
    return {
      columns: query.select.map(sel => sel.name),
      context: query.select.map(s => fromByAlias[s.tableAlias].path),
      data: result,
    };
  }, [loading, contents, query, options]);
  return {
    loading,
    table,
  };
};

export const useTableQueryCount = (query: TableQuery) => {
  const tableQuery = useTableQuery({
    ...query,
    limit: undefined,
    offset: undefined,
  });
  if (tableQuery.loading) {
    return {
      loading: true,
      count: 0,
    };
  }
  return {loading: false, count: tableQuery.table.data.length};
};

export type Table = TableMetadata | From;

export const tableIsMaterialized = (t: Table): t is TableMetadata => {
  return (t as TableMetadata).path != null;
};

export const columnTypes = (t: Table): TableColumnMetadata => {
  return tableIsMaterialized(t) ? t : t.tables[0].table;
};

export const joinedTables = (tables: Table[], joinKeys: JoinKey[]): From => {
  const from: From = {
    tables: [],
    joinKeys: [],
  };
  tables.forEach((t, i) => {
    const jk = joinKeys[i];
    if (tableIsMaterialized(t)) {
      from.tables.push({alias: i.toString(), table: t});
      from.joinKeys.push(jk);
    } else {
      t.tables.forEach((subT, j) => {
        const subJk = t.joinKeys[j];
        // This is a limitation of not handling subqueries.
        if (j === 0 && !_.isEqual(subJk, jk)) {
          throw new Error('invalid');
        }
        from.tables.push({
          alias: i.toString() + '_' + subT.alias,
          table: subT.table,
        });
        from.joinKeys.push(subJk);
      });
    }
  });
  return from;
};

export const recommendedJoin = (tables: Table[]): From | null => {
  if (
    tables.filter(t =>
      columnTypes(t).columns.find(col => col.type === 'image-file')
    ).length === tables.length
  ) {
    return joinedTables(
      tables,
      tables.map(t => {
        const col = columnTypes(t).columns.find(c => c.type === 'image-file')!;
        return {
          // TODO: we can only recommend this join if the subtables are already joined
          // using the same key we're recommending (this could be fixed by changing
          // the join structure to support subqueries)
          column: col.name,
          jsonPath: ['path'],
        };
      })
    );
  }
  return null;
};

export const metadataFromWBTable = (
  path: File.FullFilePath,
  t: MediaTable.MediaTable
): TableMetadata => {
  const types = MediaTable.detectColumnTypes(t);
  return {
    path,
    columns: types.map((type, i) => ({
      name: t.columns[i],
      type,
    })),
  };
};

export function doTableQuery(
  query: TableQuery,
  parsed: MediaTable.MediaTable[]
) {
  const {select, from} = query;
  if (from.tables.length !== from.joinKeys.length) {
    throw new Error('invalid');
  }
  const aliased = _.fromPairs(parsed.map((p, i) => [from.tables[i].alias, p]));
  const aliasedKeys = _.fromPairs(
    from.joinKeys.map((j, i) => [from.tables[i].alias, j])
  );
  let result =
    from.tables.length === 1
      ? parsed[0].data.map(row => ({
          [from.tables[0].alias]: _.fromPairs(
            parsed[0].columns.map((c, i) => [c, row[i]])
          ),
        }))
      : joinTables(aliased, aliasedKeys);

  const {where, groupBy} = query;
  // TODO: Get rid of this and replace with mongo filters, its only set
  // by SuperTable for making cell queries
  if (where != null) {
    result = result.filter((row, rowIndex) => {
      const checked = where.subs.map(cond =>
        // TODO: convoluted
        cond.col === '_index'
          ? cond.op === '='
            ? rowIndex === cond.val
            : rowIndex !== cond.val
          : cond.op === '='
          ? (_.get(row, cond.col) ?? null) === cond.val
          : (_.get(row, cond.col) ?? null) !== cond.val
      );
      if (where.comb === 'and') {
        return checked.every(o => o);
      } else {
        return checked.some(o => o);
      }
    });
  }

  const filter = query.filter ?? EMPTY_MONGO_FILTER;
  result = filterWithMongo(result, filter);

  let selectedResult: any[][] = [];

  if (groupBy != null && groupBy.length > 0) {
    const groupedRows = _.groupBy(result, row => {
      return groupBy.map(key => _.get(row, key)).join('-');
    });
    selectedResult = Object.values(groupedRows).map(rowsForGroup =>
      select.map(sel =>
        rowsForGroup.map(row => row[sel.tableAlias]?.[sel.tableColumn] ?? null)
      )
    );
  } else {
    selectedResult = result.map(row =>
      select.map(sel => row[sel.tableAlias]?.[sel.tableColumn] ?? null)
    );
  }

  const sort = getSort(query.sort)[0];
  const sortColIndex = _.findIndex(
    query.select,
    sel => sel.tableAlias + '.' + sel.tableColumn === sort.key
  );
  const sortedResult =
    sortColIndex === -1
      ? selectedResult
      : _.sortBy(selectedResult, row => {
          const val = row[sortColIndex];
          if (sort.ascending) {
            return val;
          } else {
            return -val;
          }
        });

  let finalResult = sortedResult;
  if (query.offset != null) {
    finalResult = finalResult.slice(query.offset);
  }
  if (query.limit != null) {
    finalResult = finalResult.slice(0, query.limit);
  }

  return finalResult;
}

export function allTableColumnNames(from: From) {
  return _.uniq(from.tables.flatMap(t => t.table.columns.map(c => c.name)));
}

export function allTableColumnPaths(query: TableQuery) {
  return _.uniq(
    query.from.tables.flatMap(t =>
      t.table.columns.map(c => t.alias + '.' + c.name)
    )
  );
}

export function tableCellType(query: TableQuery, colName: string): Types.Type {
  const colTypes = query.from.tables
    .map(t => t.table.columns.find(c => c.name === colName)?.type)
    .filter(Obj.notEmpty);
  if (colTypes.length === 0) {
    return null;
  }
  const colMediaType = colTypes[0];
  const type = colMediaType === 'unknown' ? null : colMediaType;
  if (colTypes.length === 1) {
    if (query.groupBy == null || query.groupBy.length === 0) {
      return type;
    }
    return {
      type: 'column',
      objectType: type,
    };
  }
  // Make sure they're all the same type for now
  if (colTypes.find(ct => ct !== colTypes[0])) {
    return null;
  }
  if (query.groupBy == null || query.groupBy.length === 0) {
    return {
      type: 'row',
      objectType: type,
    };
  }
  return {
    type: 'table',
    objectType: type,
  };
}

export function selectAllTableColsWithName(
  query: TableQuery,
  colName: string
): SelectCol[] {
  const sel: SelectCol[] = [];
  for (const table of query.from.tables) {
    const column = table.table.columns.find(c => c.name === colName);
    if (column != null) {
      sel.push({
        // TODO: what do we want name to be?
        name: table.alias + '-' + column.name,
        tableAlias: table.alias,
        tableColumn: column.name,
      });
    }
  }
  return sel;
}
