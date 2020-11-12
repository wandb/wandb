import React from 'react';
import * as Types from './types';

import {useRef} from 'react';
import * as Panel2 from './panel';
import makeComp from '../../util/profiler';
import * as Table from './table';
import {PanelComp2} from './PanelComp';

export interface PanelTableQueryConfig {
  none: false;
}

type PanelTableQueryProps = Panel2.PanelConverterProps;

const PanelTableQueryConfig: React.FC<PanelTableQueryProps> = makeComp(
  props => {
    const {updateConfig} = props;
    return (
      <PanelComp2
        input={null}
        loading={props.loading}
        panelSpec={props.child}
        configMode={true}
        config={props.config}
        context={props.context}
        updateConfig={updateConfig}
        updateContext={props.updateContext}
      />
    );
  },
  {id: 'PanelTableQueryConfig'}
);

const PanelTableQueryRender: React.FC<PanelTableQueryProps> = makeComp(
  props => {
    const {input, inputType, updateConfig} = props;

    // const [hasBeenOnScreen, setHasBeenOnScreen] = useState(false);

    const domRef = useRef<HTMLDivElement>(null);
    const tableQuery = input;
    // TODO: If we need this back, this logic doesn't work well
    // const onScreen = useOnScreen(domRef);
    // Reset this when tableQuery changes
    // useEffect(() => {
    //   if (!onScreen) {
    //     setHasBeenOnScreen(false);
    //   }
    // }, [tableQuery]);
    // useEffect(() => {
    //   if (onScreen) {
    //     setHasBeenOnScreen(true);
    //   }
    // }, [onScreen]);
    const result = Table.useTableQuery(tableQuery, {
      skip: domRef == null, // || !hasBeenOnScreen,
    });

    let childInput: any;
    if (Types.isSimpleType(inputType)) {
      throw new Error('invalid incoming type');
    }
    if (inputType.type !== 'query') {
      throw new Error('invalid incoming type');
    }
    if (Types.isSimpleType(inputType.resultType)) {
      childInput = {
        name: result.table.columns[0],
        obj: result.table.context[0],
        val: result.table.data[0]?.[0],
      };
    } else {
      childInput = result.table;
    }

    return (
      <div ref={domRef}>
        <PanelComp2
          input={childInput}
          loading={props.loading || result.loading}
          panelSpec={props.child}
          configMode={false}
          config={props.config}
          context={props.context}
          updateConfig={updateConfig}
          updateContext={props.updateContext}
        />
      </div>
    );
  },
  {id: 'PanelTableQuerySingleSimpleRender'}
);

export const PanelTableQuery: React.FC<PanelTableQueryProps> = makeComp(
  props => {
    const {configMode} = props;
    if (configMode) {
      return <PanelTableQueryConfig {...props} />;
    }
    return <PanelTableQueryRender {...props} />;
  },
  {id: 'PanelTableQuerySingleSimple'}
);

export const TableQuerySpec: Panel2.PanelConvertSpec = {
  id: 'table-query',
  Component: PanelTableQuery,
  convert: (inputType: Types.Type) => {
    if (Types.isSimpleType(inputType)) {
      return null;
    }
    if (inputType.type !== 'query') {
      return null;
    }
    return inputType.resultType;
  },
};
