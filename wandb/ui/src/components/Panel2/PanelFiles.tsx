import React from 'react';
import {useCallback, useState} from 'react';
import {Dropdown, Loader} from 'semantic-ui-react';
import * as Hooks from './hooks';
import {PanelComp2} from './PanelComp';
import * as PanelLib from './panellib/libpanel';
import * as Types from './types';
import * as Panel2 from './panel';
import * as File from './files';
import makeComp from '../../util/profiler';

const inputType = {
  type: 'row' as const,
  objectType: {
    type: 'artifact' as const,
  },
};

export interface FilesConfig {
  path?: string[];
}

type FilesProps = Panel2.PanelProps<typeof inputType, FilesConfig>;

export const FilesPanel: React.FC<FilesProps> = makeComp(
  props => {
    const {config, context, updateConfig, updateContext} = props;
    const path = config.path || [];
    const fullPath = path.join('/');

    const objectPaths = props.input.data[0];
    const paths = objectPaths.map(o => ({...o, path: fullPath}));
    const pathMetadataRaw = File.usePathMetadata(paths);
    const pathMetadata = Hooks.useGatedValue(
      pathMetadataRaw,
      pms => !pms.some(pm => pm.loading)
    );

    const newPanelContext = {
      ...context,
      path: config.path,
    };
    const files = pathMetadata.map(pm => ({
      _type: 'loaded-path' as const,
      fullPath: pm.fullPath,
      node: pm.node,
    }));

    // We currently just store configs of our previews here, keyed by previewer
    // type. This is probably not really right. Maybe use file path?
    // TODO: better config strategy
    const [subConfigs, setSubConfigs] = useState<{[key: string]: any}>({});

    const [curPanelTypeState, setCurPanelType] = useState<string | undefined>(
      undefined
    );
    // reset current previewer if not valid anymore
    let curPanelType = curPanelTypeState;
    let panelConfig = curPanelType != null ? subConfigs[curPanelType] : null;

    const type = File.getPathsType(files);
    const handlerStacks = Types.getTypeHandlerStacks(type);
    const stackIds = handlerStacks.map(PanelLib.getStackIdAndName);
    console.log('Stack Ids', stackIds);
    const columnTypeIndex = stackIds.findIndex(si => si.id === curPanelType);
    let finalInput: any = {
      // Use "row" format for now.
      // TODO: this is awkward, fix it.
      columns: files.map(f => f.fullPath.path),
      context: files.map(f => f.fullPath),
      data: [files],
    };
    if (paths.length === 1) {
      finalInput = {
        name: files[0].fullPath.path,
        obj: files[0].fullPath,
        val: files[0],
      };
    }
    const handler =
      columnTypeIndex !== -1
        ? handlerStacks[columnTypeIndex]
        : handlerStacks[0];
    if (columnTypeIndex === -1) {
      curPanelType = stackIds[0]?.id;
    }

    console.log('CUR PANEL TYPE', curPanelType);
    const setCurPanel = useCallback((key: string | undefined) => {
      console.log('SETTING CUR PANEL TYPE', key);
      setCurPanelType(key);
    }, []);
    panelConfig = curPanelType != null ? subConfigs[curPanelType] : {};

    console.log('HANDLERS', handlerStacks);
    console.log('PATH METADATA', pathMetadata);
    console.log('TYPE HANDLER', type, handler);

    const panelUpdateConfig = useCallback(
      (newConfig: any) => {
        if (curPanelType != null) {
          setSubConfigs(curSubConfigs => ({
            ...curSubConfigs,
            [curPanelType!]: newConfig,
          }));
        }
      },
      [curPanelType]
    );
    const panelUpdateContext = useCallback(
      (newContext: any) => {
        if (newContext.path != null) {
          updateConfig({path: newContext.path});
        }
        updateContext(newContext);
      },
      [updateConfig, updateContext]
    );
    /* end new types stuff */

    if (pathMetadata.some(pm => pm.loading)) {
      return <Loader active />;
    }

    return (
      <div
        className="file-browser artifact-file-browser"
        style={{display: 'flex', flexDirection: 'column', overflow: 'auto'}}>
        <div
          className="file-browser-path"
          style={{
            display: 'flex',
            alignItems: 'center',
            marginBottom: 16,
            position: 'sticky',
            left: '0px',
          }}>
          <div style={{fontSize: 24, opacity: 0.7}}>
            &gt;&nbsp;
            {['root'].concat(path).map((folderName, i) => {
              const newPath = path.slice(0, i);
              return [
                <span
                  className="file-browser-path-item"
                  style={{cursor: 'pointer'}}
                  key={'path' + i}
                  onClick={e => updateConfig({path: newPath})}>
                  {folderName}
                </span>,
                i !== path.length ? ' / ' : undefined,
              ];
            })}
          </div>

          {stackIds.length > 1 && (
            <Dropdown
              selection
              className="clone-report-modal__select"
              style={{marginLeft: 24, zIndex: 1001}}
              options={stackIds.map(si => ({
                key: si.id,
                text: si.displayName,
                value: si.id,
              }))}
              value={curPanelType}
              onChange={(e, {value}) => setCurPanel(value as string)}
            />
          )}
        </div>
        {handler != null ? (
          <PanelComp2
            input={finalInput}
            loading={false}
            panelSpec={handler}
            configMode={false}
            context={newPanelContext}
            config={panelConfig || {}}
            updateConfig={panelUpdateConfig}
            updateContext={panelUpdateContext}
          />
        ) : (
          <div>no preview</div>
        )}
      </div>
    );
  },
  {id: 'FilesPanel'}
);
