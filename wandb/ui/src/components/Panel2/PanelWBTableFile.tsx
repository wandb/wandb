import React from 'react';

import * as Panel2 from './panel';
import * as File from './files';
import * as Table from './table';
import * as MediaTable from './mediaTable';
import {Spec as PanelTableSpec, PanelTableConfig} from './PanelTable';
import * as Type from './types';

const inputType = {
  type: 'union' as const,
  members: [
    {
      type: 'wb-object-file' as const,
      mediaType: 'table' as const,
    },
    {
      type: 'row' as const,
      objectType: {
        type: 'wb-object-file' as const,
        mediaType: 'table' as const,
      },
    },
  ],
};

type PanelPreviewJupyterProps = Panel2.PanelProps<
  typeof inputType,
  PanelTableConfig
>;

const PanelPreviewWBTable: React.FC<PanelPreviewJupyterProps> = props => {
  const {context, config, updateConfig, updateContext} = props;
  const pathsWithMetdata = Type.inputIsSingle(props.input)
    ? [props.input.val]
    : props.input.data[0];
  const paths = pathsWithMetdata.map(pm => pm.fullPath);
  const files = File.usePathMetadata(paths) as File.FilePathMetadata[];

  const contents = File.useFileContent(files.map(f => f.fullPath));
  if (contents.filter(f => f.loading).length > 0) {
    return <div>loading</div>;
  }
  const tryParsed = contents.map(c => {
    if (c.contents == null) {
      return null;
    }
    try {
      return JSON.parse(c.contents) as MediaTable.MediaTable;
    } catch {
      return null;
    }
  });
  if (tryParsed.some(t => t == null)) {
    return <div>Invalid table</div>;
  }
  // ugh
  const parsed = tryParsed as MediaTable.MediaTable[];
  const materializedTables = parsed.map((pc, i) =>
    Table.metadataFromWBTable(contents[i].fullPath!, pc)
  );
  const panelContext = {
    ...context,
    tables: materializedTables,
  };
  const input = {
    columns: paths.map(p => p.path),
    context: paths,
    data: [materializedTables],
  };
  return (
    <PanelTableSpec.Component
      input={input}
      loading={props.loading}
      configMode={false}
      context={panelContext}
      config={config}
      updateConfig={updateConfig}
      updateContext={updateContext}
    />
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'wb-table-file',
  Component: PanelPreviewWBTable,
  inputType,
};
