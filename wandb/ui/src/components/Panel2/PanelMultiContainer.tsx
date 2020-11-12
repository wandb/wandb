import * as _ from 'lodash';
import React from 'react';
import {useState} from 'react';
import {Button} from 'semantic-ui-react';
import ModifiedDropdown from '../elements/ModifiedDropdown';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import * as Types from './types';
import * as Table from './table';

import * as Panel2 from './panel';
import {PanelComp2} from './PanelComp';

export interface PanelMultiContainerConfig {
  pageSize?: number;
  childConfig: any;
}
type PanelMultiContainerProps = Panel2.PanelConverterProps;

const PanelMultiContainerConfig: React.FC<PanelMultiContainerProps> = props => {
  const {config, updateConfig} = props;
  return (
    <div>
      <div>Page size</div>
      <ModifiedDropdown
        style={{marginRight: 8}}
        selection
        value={config.pageSize || 3}
        options={[1, 2, 3].map(o => ({
          key: o,
          value: o,
          text: o,
        }))}
        onChange={(e, {value}) => updateConfig({pageSize: value as number})}
      />
      <PanelComp2
        input={props.input}
        loading={props.loading}
        panelSpec={props.child}
        configMode={true}
        config={props.config}
        context={props.context}
        updateConfig={props.updateConfig}
        updateContext={props.updateContext}
      />
    </div>
  );
};

const PanelMultiContainer: React.FC<PanelMultiContainerProps> = props => {
  const {input, inputType, config} = props;
  const [pageNum, setPageNum] = useState(0);
  const pageSize = config.pageSize || 3;
  const table = input as Table.ResultTable;
  const startIndex = pageSize * pageNum;
  let endIndex = startIndex + pageSize;
  if (endIndex > table.data.length) {
    endIndex = table.data.length;
  }
  const onFirstPage = pageNum === 0;
  const onLastPage = endIndex === table.data.length;
  return (
    <div style={{display: 'flex', flexDirection: 'column'}}>
      <div
        style={{
          maxHeight: 200,
          display: 'flex',
          justifyContent: 'space-evenly',
          flexDirection: 'row',
        }}>
        {_.range(pageSize).map(offset => {
          const rowIndex = startIndex + offset;
          const row = table.data[rowIndex];
          if (row == null) {
            return <div style={{flexGrow: 1}} />;
          }
          if (Types.isSimpleType(inputType)) {
            throw new Error('invalid incoming type');
          }
          let childInput: any;
          if (inputType.type === 'table') {
            childInput = {
              columns: table.columns,
              context: table.context,
              data: [row],
            };
          } else if (inputType.type === 'column') {
            childInput = {
              name: table.columns[0],
              obj: table.context[0],
              val: row[0],
            };
          } else {
            throw new Error('invalid incoming type');
          }

          return (
            <div style={{marginRight: 8, flexBasis: 1, flexGrow: 1}}>
              <PanelComp2
                input={childInput}
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
        })}{' '}
      </div>
      <div>
        {startIndex + 1}-{endIndex} of {table.data.length}{' '}
        <Button.Group className="pagination-buttons">
          <Button
            size="tiny"
            className="wb-icon-button only-icon"
            disabled={onFirstPage}
            onClick={() => setPageNum(pageNum - 1)}>
            <LegacyWBIcon name="previous" />
          </Button>
          <Button
            size="tiny"
            className="wb-icon-button only-icon"
            disabled={onLastPage}
            onClick={() => setPageNum(pageNum + 1)}>
            <LegacyWBIcon name="next" />
          </Button>
        </Button.Group>
      </div>
    </div>
  );
};

// Note: we can use something like this to make concrete specific paged types
// instead of making all types that aren't currently pageable pageable.
// export function makeMultiContainer(spec: Panel2.PanelSpec): Panel2.PanelSpec {
//   if (spec.inputType == null) {
//     throw new Error('invalid');
//   }
//   return {
//     type: PANEL_TYPE + ' ' + spec.type,
//     Component: PanelMultiContainer,
//     available: () => false,
//     childSpec: spec,
//     inputType: {
//       type: 'query',
//       resultType: {
//         type: 'array',
//         objectType: spec.inputType,
//       },
//     },
//   };
// }

export const Spec: Panel2.PanelConvertSpec = {
  id: 'multi-container',
  displayName: 'Paged Objects',
  ConfigComponent: PanelMultiContainerConfig,
  Component: PanelMultiContainer,
  convert: (inputType: Types.Type) => {
    if (Types.isSimpleType(inputType)) {
      return null;
    }
    if (inputType.type === 'column') {
      return inputType.objectType;
    }
    if (inputType.type === 'table') {
      return {
        type: 'row',
        objectType: inputType.objectType,
      };
    }
    return null;
  },
};
