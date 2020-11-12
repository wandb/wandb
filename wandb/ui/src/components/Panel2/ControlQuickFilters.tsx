import * as _ from 'lodash';
import React from 'react';
import {Radio, Checkbox} from 'semantic-ui-react';
import * as Table from './table';
import * as Update from '../../util/update';
import makeComp from '../../util/profiler';

interface TableCompareSummaryProps {
  tableQuery: Table.TableQuery;
  updateTableQuery(tableQuery: Table.TableQuery): void;
}

export const TableCompareSummary: React.FC<TableCompareSummaryProps> = makeComp(
  props => {
    const {tableQuery, updateTableQuery} = props;
    if (tableQuery == null) {
      return <div>No tableQuery in context</div>;
    } else if (
      !Table.isJoinQuery(tableQuery) ||
      tableQuery.from.joinKeys.length <= 1
    ) {
      return <div />;
    }
    if (tableQuery.from.joinKeys.length === 2) {
      return (
        <CompareTwo
          tableQuery={tableQuery}
          updateTableQuery={updateTableQuery}
        />
      );
    }
    return (
      <CompareMany
        tableQuery={tableQuery}
        updateTableQuery={updateTableQuery}
      />
    );
  },
  {id: 'TableCompareSummary'}
);

interface FilterSetRadio {
  tableQuery: Table.TableQuery;
  pred: Table.Pred | undefined;
  text: string;
  updateTableQuery(tableQuery: Table.TableQuery): void;
}

const FilterSetRadio: React.FC<FilterSetRadio> = makeComp(
  props => {
    const {tableQuery, text, pred, updateTableQuery} = props;
    const filteredQuery = {...tableQuery, where: pred};
    const countQuery = Table.useTableQueryCount(filteredQuery);
    const checked = _.isEqual(tableQuery.where, pred);
    return (
      <div>
        <div
          style={{display: 'inline-block', cursor: 'pointer'}}
          onClick={() => updateTableQuery(filteredQuery)}>
          <Radio style={{marginRight: 4}} checked={checked} />
          {text}: {countQuery.count}
        </div>
      </div>
    );
  },
  {id: 'FilterSetRadio'}
);

const CompareTwo: React.FC<{
  tableQuery: Table.TableQuery;
  updateTableQuery(tableQuery: Table.TableQuery): void;
}> = makeComp(
  props => {
    const {tableQuery, updateTableQuery} = props;
    return (
      <div style={{position: 'sticky', left: '0px'}}>
        Quick filters
        <FilterSetRadio
          tableQuery={tableQuery}
          pred={undefined}
          text="Present in either"
          updateTableQuery={updateTableQuery}
        />
        <FilterSetRadio
          tableQuery={tableQuery}
          pred={{
            comb: 'and',
            subs: tableQuery.from.joinKeys.map((jk, i) => ({
              col: tableQuery.from.tables[i].alias + '.' + jk.column,
              op: '!=',
              val: null,
            })),
          }}
          text="Present in both"
          updateTableQuery={updateTableQuery}
        />
        <FilterSetRadio
          tableQuery={tableQuery}
          pred={{
            comb: 'and',
            subs: [
              {
                col: 0 + '.' + tableQuery.from.joinKeys[0].column,
                op: '!=',
                val: null,
              },
              {
                col: 1 + '.' + tableQuery.from.joinKeys[1].column,
                op: '=',
                val: null,
              },
            ],
          }}
          text="Only present in 0"
          updateTableQuery={updateTableQuery}
        />
        <FilterSetRadio
          tableQuery={tableQuery}
          pred={{
            comb: 'and',
            subs: [
              {
                col: 0 + '.' + tableQuery.from.joinKeys[0].column,
                op: '=',
                val: null,
              },
              {
                col: 1 + '.' + tableQuery.from.joinKeys[1].column,
                op: '!=',
                val: null,
              },
            ],
          }}
          text="Only present in 1"
          updateTableQuery={updateTableQuery}
        />
      </div>
    );
  },
  {id: 'CompareTwo'}
);

interface FilterEnableCheckboxProps {
  tableQuery: Table.TableQuery;
  comp: Table.Comparison;
  text: string;
  updateTableQuery(tableQuery: Table.TableQuery): void;
}

const FilterEnableCheckbox: React.FC<FilterEnableCheckboxProps> = makeComp(
  props => {
    const {tableQuery, text, comp, updateTableQuery} = props;
    const querySubs = tableQuery?.where?.subs || [];
    const comparisonIndex = querySubs.findIndex(c => _.isEqual(c, comp));
    const filteredQuery =
      comparisonIndex !== -1
        ? tableQuery
        : {
            ...tableQuery,
            where: {
              comb: 'and' as 'and',
              subs: [...querySubs, comp],
            },
          };
    const countQuery = Table.useTableQueryCount(filteredQuery);
    const checked = _.find(tableQuery.where?.subs ?? [], comp) != null;
    return (
      <div>
        <div
          style={{display: 'inline-block', cursor: 'pointer'}}
          onClick={() =>
            !checked
              ? updateTableQuery(filteredQuery)
              : updateTableQuery({
                  ...tableQuery,
                  where: {
                    comb: 'and',
                    subs: Update.deleteArrayIndex(querySubs, comparisonIndex),
                  },
                })
          }>
          <Checkbox style={{marginRight: 4}} checked={checked} />
          {text}: {countQuery.count}
        </div>
      </div>
    );
  },
  {id: 'FilterEnableCheckbox'}
);

const CompareMany: React.FC<{
  tableQuery: Table.TableQuery;
  updateTableQuery(tableQuery: Table.TableQuery): void;
}> = makeComp(
  props => {
    const {tableQuery, updateTableQuery} = props;
    return (
      <div>
        Quick filters
        {tableQuery.from.joinKeys.map((jk, i) => {
          const colName = tableQuery.from.tables[i].alias + '.' + jk.column;
          const tablePath = tableQuery.from.tables[i].table.path;
          return (
            <FilterEnableCheckbox
              tableQuery={tableQuery}
              comp={{
                col: colName,
                op: '!=',
                val: null,
              }}
              text={`Present in ${tablePath.artifactCommitHash}/${tablePath.path}.${jk.column}`}
              updateTableQuery={updateTableQuery}
            />
          );
        })}
      </div>
    );
  },
  {id: 'CompareMany'}
);
