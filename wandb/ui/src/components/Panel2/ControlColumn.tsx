// import 'semantic/dist/semantic.css';
import React, {useState} from 'react';
import ModifiedDropdown from '../elements/ModifiedDropdown';
import {Button, Input, Popup} from 'semantic-ui-react';
import {TableQuery} from './table';
import {TableColumn} from './controlsTableColumn';
import * as Update from '../../util/update';
import * as Panel2 from './panel';
import * as PanelLib from './panellib/libpanel';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import makeComp from '../../util/profiler';
import * as Types from './types';
import * as Table from './table';
import {PanelComp2} from './PanelComp';

interface ColumnControlProps {
  query: TableQuery;
  panelContext: Panel2.PanelContext;
  keys: string[];
  allowAgg: boolean;
  columns: TableColumn[];
  updateContext: Panel2.UpdateContext;
  setColumns(columns: TableColumn[]): void;
}

const STYLE_POPUP_CLASS = 'line-style-buttons';
export const ColumnControl: React.FC<ColumnControlProps> = makeComp(
  props => {
    const {query, columns, panelContext, setColumns, updateContext} = props;
    const [open, setOpen] = useState(false);

    const availInputCols = Table.allTableColumnNames(query.from);

    const rowType: {[key: string]: Types.SimpleType} = {};
    for (const sel of query.select) {
      const table = query.from.tables.find(t => t.alias === sel.tableAlias);
      if (table == null) {
        throw new Error('invalid');
      }
      const col = table.table.columns.find(c => c.name === sel.tableColumn);
      if (col == null) {
        throw new Error('invalid');
      }
      rowType[sel.name] = col.type === 'unknown' ? null : col.type;
    }

    return (
      <Popup
        basic
        className="wb-table-action-popup"
        on="click"
        position="bottom left"
        trigger={
          <Button
            data-test="group-popup"
            size="tiny"
            className={'wb-icon-button table-columns-button'}>
            <LegacyWBIcon name="columns" title={'Columns'} />
            Columns
          </Button>
        }
        content={
          <div>
            {columns.map((c, i) => {
              const type: Types.Type = Table.tableCellType(query, c.inputCol);
              const handlerStacks = Types.getTypeHandlerStacks(type);
              const stackIds = handlerStacks.map(PanelLib.getStackIdAndName);
              const columnTypeIndex = stackIds.findIndex(
                si => si.id === c.type
              );
              const colType =
                columnTypeIndex !== -1
                  ? stackIds[columnTypeIndex].id
                  : stackIds[0].id;
              const handler =
                columnTypeIndex !== -1
                  ? handlerStacks[columnTypeIndex]
                  : handlerStacks[0];
              // TODO: what if handler is undefined?
              // console.log(
              //   'CONFIG HANDLER STACKS',
              //   handlerStacks,
              //   Panel2.getLeafPanelType(handler)
              // );

              return (
                <div
                  // TODO: Use a better key to support column reordering without remount
                  key={i}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    marginBottom: 16,
                  }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      marginBottom: 8,
                    }}>
                    <Input
                      style={{marginRight: 8}}
                      placeholder="column name"
                      value={c.name}
                      onChange={(e, {value}) =>
                        setColumns(
                          Update.updateArrayIndex(columns, i, {
                            ...c,
                            name: value as string,
                          })
                        )
                      }
                    />
                    <ModifiedDropdown
                      style={{marginRight: 8}}
                      selection
                      value={colType}
                      options={stackIds.map(si => ({
                        key: si.id,
                        value: si.id,
                        text: si.displayName,
                      }))}
                      onChange={(e, {value}) =>
                        setColumns(
                          Update.updateArrayIndex(columns, i, {
                            ...c,
                            type: value as any, // TODO: bad type
                          })
                        )
                      }
                    />
                    <ModifiedDropdown
                      style={{marginRight: 8}}
                      selection
                      value={c.inputCol}
                      options={availInputCols.map(o => ({
                        key: o,
                        value: o,
                        text: o,
                      }))}
                      onChange={(e, {value}) =>
                        setColumns(
                          Update.updateArrayIndex(columns, i, {
                            ...c,
                            inputCol: value as any,
                          })
                        )
                      }
                    />
                    <Button
                      size="tiny"
                      className={
                        'enable-pointer-events wb-icon-button only-icon'
                      }
                      onClick={() => {
                        setColumns(Update.deleteArrayIndex(columns, i));
                      }}>
                      <LegacyWBIcon name="delete" />
                    </Button>
                  </div>
                  {handler != null && (
                    <PanelComp2
                      configMode={true}
                      loading={false}
                      input={query}
                      panelSpec={handler}
                      context={panelContext}
                      config={(c as any).config || {}}
                      updateConfig={(newConfig: any) => {
                        setColumns(
                          Update.updateArrayIndex(columns, i, {
                            ...c,
                            config: {
                              ...(c as any).config,
                              ...newConfig,
                            },
                          } as any)
                        );
                      }}
                      updateContext={updateContext}
                    />
                  )}
                </div>
              );
            })}
            <Button
              size="tiny"
              onClick={() =>
                setColumns([
                  ...columns,
                  {
                    name: '',
                    inputCol: availInputCols[0],
                    type: 'AutoQuery',
                    config: {},
                  },
                ])
              }>
              + Add column
            </Button>
          </div>
        }
        open={open}
        onClose={e => {
          const nestedPopupSelector = [STYLE_POPUP_CLASS]
            .map(c => '.' + c)
            .join(', ');

          const inPopup =
            (e.target as HTMLElement).closest(nestedPopupSelector) != null;

          if (!inPopup) {
            setOpen(false);
          }
        }}
        onOpen={() => setOpen(true)}
        popperModifiers={{
          preventOverflow: {enabled: false},
          flip: {enabled: false},
        }}
      />
    );
  },
  {id: 'ColumnControl'}
);
