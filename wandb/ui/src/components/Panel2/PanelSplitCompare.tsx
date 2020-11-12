import React from 'react';
import {Divider} from 'semantic-ui-react';
import * as Types from './types';
import * as Table from './table';

import * as Panel2 from './panel';
import {PanelComp2} from './PanelComp';

type PanelSplitCompareProps = Panel2.PanelConverterProps;

const PanelSplitCompare: React.FC<PanelSplitCompareProps> = props => {
  const {input} = props;
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
            <PanelComp2
              input={{
                name: table.columns[i],
                obj,
                val,
              }}
              loading={props.loading}
              panelSpec={props.child}
              configMode={false}
              config={props.config}
              context={props.context}
              updateConfig={props.updateConfig}
              updateContext={props.updateContext}
            />
          </div>
        );
      })}
    </div>
  );
};

export const Spec: Panel2.PanelConvertSpec = {
  id: 'split-panel',
  Component: PanelSplitCompare,
  convert: (inputType: Types.Type) => {
    if (Types.isSimpleType(inputType)) {
      return null;
    }
    if (inputType.type !== 'row') {
      return null;
    }
    return inputType.objectType;
  },
};
