import React from 'react';

import * as Panel2 from './panel';
import * as File from './files';
import * as Table from './table';
import {Spec as PanelTableSpec, PanelTableConfig} from './PanelTable';
import * as Type from './types';
import * as Obj from '../../util/obj';

const inputType = {
  type: 'union' as const,
  members: [
    {
      type: 'wb-object-file' as const,
      mediaType: 'joined-table' as const,
    },
    {
      type: 'row' as const,
      objectType: {
        type: 'wb-object-file' as const,
        mediaType: 'joined-table' as const,
      },
    },
  ],
};

type PanelPreviewWBJoinedTableProps = Panel2.PanelProps<
  typeof inputType,
  PanelTableConfig
>;

const PanelPreviewWBJoinedTable: React.FC<PanelPreviewWBJoinedTableProps> = props => {
  const {config, context, updateConfig, updateContext} = props;
  const pathsWithMetdata = Type.inputIsSingle(props.input)
    ? [props.input.val]
    : props.input.data[0];
  const paths = pathsWithMetdata.map(pm => pm.fullPath);

  const contents = File.useFileContent(paths);
  const contentsLoading = contents.filter(f => f.loading).length > 0;

  let parsedContents: any[] = [];
  if (!contentsLoading) {
    parsedContents = contents.map(f => {
      try {
        if (f.contents == null) {
          throw new Error('invalid');
        }
        return JSON.parse(f.contents);
      } catch {
        // TODO
        throw new Error('invalid json');
      }
    });
  }

  const table1Paths = parsedContents.map((p, i) => ({
    ...paths[i],
    path: p.table1,
  }));
  const table1Contents = File.useFileContent(table1Paths, {
    skip: contentsLoading,
  });
  const table2Paths = parsedContents.map((p, i) => ({
    ...paths[i],
    path: p.table2,
  }));
  const table2Contents = File.useFileContent(table2Paths, {
    skip: contentsLoading,
  });

  if (
    contentsLoading ||
    table1Contents.filter(f => f.loading).length > 0 ||
    table2Contents.filter(f => f.loading).length > 0
  ) {
    return <div>loading</div>;
  }

  const tableMetadatas = parsedContents.map((pc, i) => {
    return {
      tables: [
        Table.metadataFromWBTable(
          table1Contents[i].fullPath!,
          JSON.parse(table1Contents[i].contents!)
        ),
        Table.metadataFromWBTable(
          table2Contents[i].fullPath!,
          JSON.parse(table2Contents[i].contents!)
        ),
      ],
      joinKey: parsedContents[i].join_key ?? null,
    };
  });
  const joined = tableMetadatas.map(
    (joinTableMetadata: {tables: Table.Table[]; joinKey: string | null}) => {
      if (joinTableMetadata.joinKey == null) {
        throw new Error('JoinedTable missing join_key');
      }
      return Table.joinedTables(
        joinTableMetadata.tables,
        joinTableMetadata.tables.map(_ => ({
          column: joinTableMetadata.joinKey!,
        }))
      );
    }
  );

  const nonEmptyJoined = joined.filter(Obj.notEmpty);

  const input = {
    columns: paths.map(p => p.path),
    context: paths,
    data: [nonEmptyJoined],
  };

  return (
    <PanelTableSpec.Component
      input={input}
      loading={props.loading}
      configMode={false}
      context={context}
      config={config}
      updateConfig={updateConfig}
      updateContext={updateContext}
    />
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'wb-joined-table',
  Component: PanelPreviewWBJoinedTable,
  inputType,
};
