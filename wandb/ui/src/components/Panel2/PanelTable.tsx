import React from 'react';

import * as Panel2 from './panel';
import {Button, Icon, Divider, Popup} from 'semantic-ui-react';
import {SortControl} from './ControlSort';
import {GroupByControl} from './ControlGroupBy';
import {ColumnControl} from './ControlColumn';
import {PageControl} from './ControlPage';
import {TableCompareSummary} from './ControlQuickFilters';
import {SuperTable} from './SuperTable';
import * as Table from './table';
import makeComp from '../../util/profiler';
import {FilterControl} from './ControlFilter';
import {TableColumn} from './controlsTableColumn';

const inputType = {
  type: 'row' as const,
  objectType: {
    type: 'table-info' as const,
  },
};

export interface PanelTableConfig {
  keys?: string[];
  tableConfigs?: {
    [key: string]: ConfigurableTableConfig;
  };
}

type PanelTableProps = Panel2.PanelProps<typeof inputType, PanelTableConfig>;

const PanelTable: React.FC<PanelTableProps> = props => {
  const {config, context, updateConfig, updateContext} = props;
  const tableConfigs = config.tableConfigs || {};
  const tables = props.input.data[0];
  if (tables == null) {
    throw new Error('invalid context for PanelTable');
  }

  if (tables.length > 0 && !Table.tableIsMaterialized(tables[0])) {
    return (
      <AutoColsTable
        tables={tables}
        joinKeys={(tables[0] as Table.From).joinKeys}
        tableConfig={tableConfigs.all || {}}
        updateConfig={newConfig =>
          updateConfig({tableConfigs: {...tableConfigs, all: newConfig}})
        }
        updateContext={updateContext}
        context={context}
      />
    );
  } else if (
    tables.filter(t =>
      Table.columnTypes(t).columns.find(col => col.type === 'image-file')
    ).length === tables.length
  ) {
    const joinKeys = tables.map((t, i) => {
      const col = Table.columnTypes(t).columns.find(
        c => c.type === 'image-file'
      )!;
      return {
        column: col.name,
        jsonPath: ['path'],
      };
    });
    return (
      <AutoColsTable
        tables={tables}
        joinKeys={joinKeys}
        tableConfig={tableConfigs.all || {}}
        updateConfig={newConfig =>
          updateConfig({tableConfigs: {...tableConfigs, all: newConfig}})
        }
        updateContext={updateContext}
        context={context}
      />
    );
  } else {
    return (
      <div>
        {tables.map((t, i) => (
          <div key={i} style={{marginBottom: 48}}>
            {props.input.context[i].artifactCommitHash}
            <AutoColsTable
              tables={[t]}
              joinKeys={[{column: '?'}]}
              tableConfig={tableConfigs.all || {}}
              updateConfig={newConfig =>
                updateConfig({
                  tableConfigs: {...tableConfigs, all: newConfig},
                })
              }
              updateContext={updateContext}
              context={context}
            />
          </div>
        ))}
      </div>
    );
  }
};

export const Spec: Panel2.PanelSpec = {
  id: 'table',
  Component: PanelTable,
  inputType,
};

const AutoColsTable: React.FC<{
  tables: Table.Table[];
  joinKeys: Table.JoinKey[];
  tableConfig: ConfigurableTableConfig;
  updateConfig: (newConfig: ConfigurableTableConfig) => void;
  updateContext: Panel2.UpdateContext;
  context: Panel2.PanelContext;
}> = makeComp(
  props => {
    const {
      tables,
      joinKeys,
      tableConfig,
      updateConfig,
      updateContext,
      context,
    } = props;
    const joined = Table.joinedTables(tables, joinKeys);
    const select: Table.SelectCol[] = [];
    const columns: TableColumn[] = [];
    const allColNames = Table.allTableColumnNames(joined);

    allColNames.forEach((colName, i) => {
      columns.push({
        name: colName,
        inputCol: colName,
        type: 'auto',
        config: {},
      });
    });

    const query = {
      select,
      from: joined,
    };

    return (
      <>
        <TableCompareSummary
          tableQuery={{
            ...query,
            where: tableConfig != null ? tableConfig.pred : undefined,
          }}
          updateTableQuery={newQuery => {
            updateConfig({
              ...tableConfig,
              pred: newQuery.where,
            });
          }}
        />
        <Divider />
        <ConfigurableTable
          baseQuery={{
            ...query,
          }}
          config={tableConfig}
          updateConfig={newConfig => {
            updateConfig({
              ...tableConfig,
              ...newConfig,
            });
          }}
          updateContext={updateContext}
          panelContext={{classSets: context.classSets}}
          defaultColumns={columns}
        />
      </>
    );
  },
  {id: 'AutoColsTable'}
);

interface ConfigurableTableConfig {
  sort?: Table.Sort;
  filter?: Table.MongoFilter;
  groupBy?: Table.GroupBy;
  columns?: TableColumn[];

  pred?: Table.Pred;

  offset?: number;
  limit?: number;
  displayMode?: 'table' | 'grid';
}

interface ConfigurableTableProps {
  config?: ConfigurableTableConfig;
  baseQuery: Table.TableQuery;

  panelContext: Panel2.PanelContext;
  defaultColumns: TableColumn[];
  updateContext: Panel2.UpdateContext;
  updateConfig(newConfig: Partial<ConfigurableTableConfig>): void;
}

const ConfigurableTable: React.FC<ConfigurableTableProps> = makeComp(
  props => {
    const {baseQuery, panelContext, updateConfig, updateContext} = props;
    const config = props.config ?? {};
    const sort = config.sort ?? [];
    const groupBy = config.groupBy ?? [];
    const columns = config.columns ?? props.defaultColumns;
    const offset = config.offset ?? 0;
    const displayMode = config.displayMode ?? 'table';
    const limit = displayMode === 'table' ? 10 : 9;
    const pred = config.pred;

    const keys = Table.allTableColumnPaths(baseQuery);

    const tableQuery = {
      ...baseQuery,
      groupBy,
      filter: config.filter,
      sort,
      offset,
      where: pred,
      limit,
    };

    const newContext = {
      ...panelContext,
      tableQuery,
    };

    return (
      <>
        <div
          style={{
            backgroundColor: '#f9f9f9',
            marginBottom: 0,
            paddingBottom: '5px',
            position: 'sticky',
            top: -50,
            left: 0,
            zIndex: 1000,
            width: '100%',
          }}>
          <>
            <div style={{marginBottom: 8}}>
              {tableQuery.from.tables.length === 1 ? (
                <span>Table: </span>
              ) : (
                <span>Joined tables: </span>
              )}
              {tableQuery.from.tables.map(t => {
                const path = t.table.path.path;
                const tName = path.endsWith('.table.json')
                  ? path.slice(0, path.length - 11)
                  : path;
                return (
                  <Popup
                    key={path}
                    hoverable
                    trigger={
                      <span
                        style={{
                          marginRight: 8,
                          textDecoration: 'underline',
                          color: '#007faf',
                        }}>
                        {t.alias}: {tName}
                      </span>
                    }
                    content={
                      <div style={{maxHeight: 400, overflow: 'auto'}}>
                        <pre>{JSON.stringify(t, undefined, 2)}</pre>
                      </div>
                    }
                  />
                );
              })}
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                width: '100%',
              }}>
              <div>
                <FilterControl
                  filter={config.filter}
                  setFilter={newFilter => updateConfig({filter: newFilter})}
                />
                <GroupByControl
                  keys={keys}
                  groupBy={config.groupBy || []}
                  setGroupBy={newGroupBy => {
                    if (newGroupBy.length === 0) {
                      const newColumns = config.columns?.map(c =>
                        c.type.startsWith('MultiContainer')
                          ? {
                              type: 'Image',
                              config: c.config.childConfig,
                              inputCol: c.inputCol,
                              name: c.name,
                            }
                          : c.type === 'Histogram'
                          ? {
                              type: 'Number',
                              config: {},
                              inputCol: c.inputCol,
                              name: c.name,
                            }
                          : c
                      );
                      updateConfig({groupBy: newGroupBy, columns: newColumns});
                    } else {
                      const newColumns = config.columns?.map(c =>
                        c.type === 'Image'
                          ? {
                              type: 'MultiContainer Image',
                              config: {
                                childConfig: c.config,
                              },
                              inputCol: c.inputCol,
                              name: c.name,
                            }
                          : c.type === 'Number'
                          ? {
                              type: 'Histogram',
                              config: c.config.childConfig,
                              inputCol: c.inputCol,
                              name: c.name,
                            }
                          : c.type === 'BarChart'
                          ? {
                              type: 'auto',
                              config: c.config,
                              inputCol: c.inputCol,
                              name: c.name,
                            }
                          : c
                      );
                      updateConfig({groupBy: newGroupBy, columns: newColumns});
                    }
                  }}
                />
                <SortControl
                  keys={keys}
                  sort={sort}
                  setSort={newSort => updateConfig({sort: newSort})}
                />
                <ColumnControl
                  keys={keys}
                  query={tableQuery}
                  panelContext={newContext}
                  allowAgg={groupBy.length > 0}
                  columns={columns}
                  setColumns={newColumns => updateConfig({columns: newColumns})}
                  updateContext={updateContext}
                />
                <Popup
                  hoverable
                  trigger={
                    <div
                      style={{
                        color: '#007faf',
                        textDecoration: 'underline',
                        display: 'inline-block',
                        cursor: 'pointer',
                        marginRight: 16,
                      }}>
                      Raw query
                    </div>
                  }
                  content={
                    <div style={{maxHeight: 400, overflow: 'auto'}}>
                      <pre>{JSON.stringify(tableQuery, undefined, 2)}</pre>
                    </div>
                  }
                />
              </div>
              <div>
                <Button.Group size="tiny">
                  <Button
                    style={{
                      backgroundColor:
                        displayMode === 'table' ? '#03b7b7' : undefined,
                    }}
                    icon
                    onClick={() => updateConfig({displayMode: 'table'})}>
                    <Icon name="table" />
                  </Button>
                  <Button
                    style={{
                      backgroundColor:
                        displayMode === 'grid' ? '#03b7b7' : undefined,
                    }}
                    icon
                    onClick={() => updateConfig({displayMode: 'grid'})}>
                    <Icon name="grid layout" />
                  </Button>
                </Button.Group>
                <PageControl
                  query={tableQuery}
                  pageParams={{offset, limit}}
                  updatePageParams={({offset: newOffset, limit: newLimit}) =>
                    updateConfig({offset: newOffset, limit: newLimit})
                  }
                />
              </div>
            </div>
          </>
        </div>
        <SuperTable
          query={tableQuery}
          context={newContext}
          updateConfig={updateConfig}
          updateContext={updateContext}
          columns={columns}
          displayMode={displayMode}
        />
      </>
    );
  },
  {id: 'ConfigurableTable'}
);
