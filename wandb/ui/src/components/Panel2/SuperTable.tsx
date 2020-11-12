import * as _ from 'lodash';
import * as React from 'react';
import {Table, Grid} from 'semantic-ui-react';
import * as Panel2 from './panel';
import * as Update from '../../util/update';
import {TableQuery, useTableQuery} from './table';
import {TableColumn} from './controlsTableColumn';
import makeComp from '../../util/profiler';
import * as PanelLib from './panellib/libpanel';
import * as TableLib from './table';
import * as Types from './types';
import {PanelComp2} from './PanelComp';
import * as String from '../../util/string';

interface SuperTableProps {
  query: TableQuery;
  context: Panel2.PanelContext;

  columns: TableColumn[];
  displayMode: 'table' | 'grid';
  updateContext: Panel2.UpdateContext;
  updateConfig(newConfig: any): void;
}

export const SuperTable: React.FC<SuperTableProps> = makeComp(
  props => {
    const {columns, displayMode, context, updateConfig, updateContext} = props;

    let {query} = props;

    if (query.groupBy != null && query.groupBy.length > 0) {
      const [tableAlias, tableColumn] = String.splitOnce(query.groupBy[0], '.');
      if (tableColumn == null) {
        throw new Error('invalid');
      }
      // Select a single column for the group key
      query = {
        ...query,
        select: [
          {
            name: 'groupkey-0',
            tableAlias,
            tableColumn,
          },
        ],
      };
    }

    const columnSelections = columns.map(c =>
      TableLib.selectAllTableColsWithName(query, c.inputCol)
    );

    // Flatten the columnSelections out into a single select statement for the
    // query, but construct a reverse index mapping while we flatten so we
    // can separate the results back out for each column.
    const select: TableLib.SelectCol[] = [];
    const columnIndexToSelectIndices: number[][] = [];
    columnSelections.forEach(cs => {
      const columnSelectIndicies: number[] = [];
      cs.forEach((sel, i) => {
        columnSelectIndicies.push(select.length);
        select.push(sel);
      });
      columnIndexToSelectIndices.push(columnSelectIndicies);
    });
    query = {
      ...query,
      select,
    };

    const tableQuery = useTableQuery(query);
    if (tableQuery.loading) {
      return <div>Loading</div>;
    }

    const table = tableQuery.table;

    const grouped = query.groupBy != null && query.groupBy.length > 0;

    const gridCols = 3;
    const gridRows = Math.ceil(table.data.length / gridCols);

    // Each cell receives its own sub-table for its row/column of results
    const makeCellTable = (row: any, columnIndex: number) => {
      const selectIndices = columnIndexToSelectIndices[columnIndex];
      return {
        columns: selectIndices.map(si => table.columns[si]),
        context: selectIndices.map(si => table.context[si]),
        data:
          // Columns of grouped queries with no aggregation come back as
          // arrays. Transpose the arrays for this cell.
          query.groupBy != null && query.groupBy.length > 0
            ? _.zip(...selectIndices.map(si => row[si]))
            : [selectIndices.map(si => row[si])],
      };
    };

    return displayMode === 'table' ? (
      <Table>
        <Table.Header>
          <Table.Row>
            {columns.map((c, i) => {
              return (
                <Table.HeaderCell
                  style={{
                    position: 'sticky',
                    top: 24,
                    zIndex: 999,
                    padding: '8px 16px',
                    borderTop: '1px solid #eee',
                    whiteSpace: 'nowrap',
                  }}
                  key={i}>
                  {c.name}
                </Table.HeaderCell>
              );
            })}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {table.data.map((row, rowIndex) => (
            <Table.Row key={rowIndex}>
              {columns.map((c, i) => (
                // override a style that we set in semantic that shouldn't apply here
                // .file-browser td {max-width}
                <Table.Cell
                  style={{
                    maxWidth: 'none',
                    borderRight: '1px solid #eee',
                  }}
                  key={i}>
                  <CellContents
                    col={c}
                    grouped={grouped}
                    cellTable={makeCellTable(row, i)}
                    query={query}
                    panelContext={context}
                    updateConfig={(newColConfig: any) =>
                      updateConfig({
                        columns: Update.updateArrayIndex(columns, i, {
                          ...c,
                          config: {
                            ...(c as any).config,
                            ...newColConfig,
                          },
                        } as any),
                      })
                    }
                    updateContext={updateContext}
                  />
                </Table.Cell>
              ))}
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    ) : (
      <Grid columns={gridCols}>
        {_.range(gridRows).map(gridRow => (
          <Grid.Row key={gridRow}>
            {_.range(gridCols).map(gridCol => {
              const rowIndex = gridRow * gridCols + gridCol;
              const row = table.data[rowIndex];
              if (row == null) {
                return undefined;
              }
              return (
                <Grid.Column
                  key={gridCol}
                  style={{display: 'flex', maxWidth: '100%'}}>
                  {columns.map((c, i) => (
                    <div
                      key={i}
                      style={{
                        maxWidth: '100%',
                        overflow: 'hidden',
                        whiteSpace: 'nowrap',
                        textOverflow: 'ellipsis',
                      }}>
                      <CellContents
                        col={c}
                        cellTable={makeCellTable(row, i)}
                        grouped={grouped}
                        query={query}
                        panelContext={context}
                        updateConfig={(newColConfig: any) =>
                          updateConfig({
                            columns: Update.updateArrayIndex(columns, i, {
                              ...c,
                              config: {
                                ...(c as any).config,
                                ...newColConfig,
                              },
                            } as any),
                          })
                        }
                        updateContext={updateContext}
                      />
                    </div>
                  ))}
                </Grid.Column>
              );
            })}
          </Grid.Row>
        ))}
      </Grid>
    );
  },
  {id: 'SuperTable'}
);

const CellContents = makeComp(
  (props: {
    col: TableColumn;
    grouped: boolean;
    cellTable: TableLib.ResultTable;
    query: TableQuery;
    panelContext: Panel2.PanelContext;
    updateConfig: any;
    updateContext: Panel2.UpdateContext;
  }) => {
    const {
      col: c,
      query,
      panelContext,
      cellTable,
      updateConfig,
      updateContext,
    } = props;

    const type: Types.Type = TableLib.tableCellType(query, c.inputCol);
    const handlerStacks = Types.getTypeHandlerStacks(type);
    const stackIds = handlerStacks.map(PanelLib.getStackIdAndName);
    const columnTypeIndex = stackIds.findIndex(si => si.id === c.type);

    let finalInput: any = cellTable;
    if (Types.isSimpleType(type)) {
      finalInput = {
        name: cellTable.columns[0],
        obj: cellTable.context[0],
        val: cellTable.data[0]?.[0],
      };
    }
    const handler =
      columnTypeIndex !== -1
        ? handlerStacks[columnTypeIndex]
        : handlerStacks[0];

    return (
      <div
        style={{
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
        }}>
        {handler != null ? (
          <PanelComp2
            input={finalInput}
            loading={false}
            panelSpec={handler}
            configMode={false}
            context={panelContext}
            config={c.config as any}
            updateConfig={updateConfig}
            updateContext={updateContext}
          />
        ) : (
          <div>No handler</div>
        )}
      </div>
    );
  },
  {id: 'CellContents'}
);
