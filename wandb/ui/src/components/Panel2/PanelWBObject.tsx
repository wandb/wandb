import React from 'react';
import {useMemo} from 'react';
import * as Types from './types';
import * as File from './files';

import * as Panel2 from './panel';
import {PanelComp2} from './PanelComp';

type PanelWBObjectProps = Panel2.PanelConverterProps;

const PanelWBObject: React.FC<PanelWBObjectProps> = props => {
  const pathObj = props.input;
  const path = pathObj.val.path;
  const contents = File.useFileContent([path])[0];
  const parsed = useMemo(() => {
    if (contents.loading) {
      return null;
    }
    try {
      return JSON.parse(contents.contents!);
    } catch {
      // pass
    }
    return null;
  }, [contents]);

  if (contents.loading) {
    return <div>Loading</div>;
  }
  if (parsed == null) {
    return <div>{"Couldn't parse W&B media object"}</div>;
  }

  console.log('PARSED', parsed);

  return (
    <div>
      <PanelComp2
        input={{
          name: pathObj.name,
          obj: pathObj.obj,
          val: parsed,
        }}
        loading={props.loading}
        panelSpec={props.child}
        configMode={true}
        config={props.config}
        context={props.context}
        updateConfig={props.updateConfig}
        updateContext={props.updateContext}
      />
      <PanelComp2
        input={{
          name: pathObj.name,
          obj: pathObj.obj,
          val: parsed,
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
};

export const Spec: Panel2.PanelConvertSpec = {
  id: 'wb-object-file',
  Component: PanelWBObject,
  convert: (inputType: Types.Type) => {
    if (Types.isSimpleType(inputType)) {
      return null;
    }
    if (inputType.type !== 'wb-object-file') {
      return null;
    }
    return inputType.mediaType;
  },
};
