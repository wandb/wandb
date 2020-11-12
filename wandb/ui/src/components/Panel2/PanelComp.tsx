import * as React from 'react';
import * as Panel2 from './panel';
import * as PanelLib from './panellib/libpanel';
import makeComp from '../../util/profiler';

export const PanelComp2 = makeComp(
  (props: {
    panelSpec: Panel2.PanelSpecNode;
    input?: any;
    context: Panel2.PanelContext;
    config: any;
    loading: boolean;
    configMode: boolean;
    updateConfig(partialConfig: Partial<any>): void;
    updateContext(partialConfig: Partial<Panel2.PanelContext>): void;
  }) => {
    const {panelSpec} = props;
    if (PanelLib.isWithChild(panelSpec)) {
      if (props.configMode) {
        const ConfigComp = panelSpec.ConfigComponent;
        if (ConfigComp == null) {
          return <PanelComp2 {...props} panelSpec={panelSpec.child} />;
        }
        return (
          <ConfigComp
            input={props.input}
            context={props.context}
            loading={props.loading}
            inputType={panelSpec.inputType}
            child={panelSpec.child}
            configMode={props.configMode}
            config={props.config}
            updateConfig={props.updateConfig}
            updateContext={props.updateContext}
          />
        );
      }
      const Comp = panelSpec.Component;
      return (
        <Comp
          input={props.input}
          context={props.context}
          loading={props.loading}
          inputType={panelSpec.inputType}
          child={panelSpec.child}
          configMode={props.configMode}
          config={props.config}
          updateConfig={props.updateConfig}
          updateContext={props.updateContext}
        />
      );
    } else {
      if (props.configMode) {
        const ConfigComp = panelSpec.ConfigComponent;
        if (ConfigComp == null) {
          return <div />;
        }
        return (
          <ConfigComp
            input={props.input}
            context={props.context}
            loading={props.loading}
            configMode={props.configMode}
            config={props.config}
            updateConfig={props.updateConfig}
            updateContext={props.updateContext}
          />
        );
      }
      const Comp = panelSpec.Component;
      return (
        <Comp
          configMode={props.configMode}
          context={props.context}
          loading={props.loading}
          input={props.input}
          config={props.config}
          updateConfig={props.updateConfig}
          updateContext={props.updateContext}
        />
      );
    }
  },
  {id: 'PanelComp'}
);
