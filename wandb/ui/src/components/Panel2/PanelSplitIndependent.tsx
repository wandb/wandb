import React from 'react';
import {useMemo} from 'react';
import {Divider, Dropdown} from 'semantic-ui-react';
import * as Table from './table';
import * as Types from './types';
import * as Panel2 from './panel';
import * as PanelLib from './panellib/libpanel';
import {PanelComp2} from './PanelComp';
import * as File from './files';

const inputType = {
  type: 'row' as const,
  objectType: 'any' as const,
};

export interface PanelSplitCompareConfig {
  panelChoices?: {
    [slot: number]: {
      id: string;
      config: any;
    };
  };
}
type PanelSplitCompareProps = Panel2.PanelProps<
  typeof inputType,
  PanelSplitCompareConfig
>;

const PanelSplitCompare: React.FC<PanelSplitCompareProps> = props => {
  const {input, config, updateConfig} = props;
  const panelChoices = useMemo(() => config.panelChoices ?? {}, [
    config.panelChoices,
  ]);
  const table = input as Table.ResultTable;
  const row = table.data[0];
  return (
    <div
      style={{
        display: 'flex',
        flexGrow: 1,
        flexDirection: 'row',
        width: '100%',
      }}>
      {row.map((val, i) => {
        // const pathMetadata = pathMetadatas[0];
        const obj = table.context[i];
        if (!File.isLoadedPathMetadata(val)) {
          return <div>Unknown object type</div>;
        }
        const type = File.getPathType(val);
        const handlerStacks = Types.getTypeHandlerStacks(type);
        const stackIds = handlerStacks.map(PanelLib.getStackIdAndName);
        let curPanelId = panelChoices[i]?.id;
        const columnTypeIndex = stackIds.findIndex(si => si.id === curPanelId);
        const handler =
          columnTypeIndex !== -1
            ? handlerStacks[columnTypeIndex]
            : handlerStacks[0];
        if (columnTypeIndex === -1) {
          curPanelId = stackIds[0]?.id;
        }
        if (curPanelId == null) {
          return <div>No handler</div>;
        }
        return (
          <div
            key={obj.artifactCommitHash}
            style={{
              display: 'flex',
              flexDirection: 'column',
              flexBasis: '100%',
              flex: 1,
              paddingRight: 32,
              overflowX: 'auto',
              overflowY: 'visible',
            }}>
            <div>
              {/* TODO: display better paths */}
              {obj.artifactCommitHash}
            </div>
            <Divider />
            <Dropdown
              selection
              className="clone-report-modal__select"
              style={{zIndex: 1001}}
              options={stackIds.map(si => ({
                key: si.id,
                text: si.displayName,
                value: si.id,
              }))}
              value={curPanelId}
              onChange={(e, {value}) =>
                updateConfig({
                  panelChoices: {
                    ...panelChoices,
                    [i]: {id: value as string, config: {}},
                  },
                })
              }
            />
            <PanelComp2
              input={{
                name: table.columns[i],
                obj,
                val,
              }}
              loading={props.loading}
              panelSpec={handler}
              configMode={false}
              config={props.config}
              context={props.context}
              updateConfig={newConfig =>
                updateConfig({
                  panelChoices: {
                    ...panelChoices,
                    [i]: {...panelChoices?.[i], config: newConfig},
                  },
                })
              }
              updateContext={props.updateContext}
            />
          </div>
        );
      })}
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'split-panel-independent',
  Component: PanelSplitCompare,
  inputType,
};
