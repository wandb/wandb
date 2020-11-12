import React from 'react';
import {useMemo} from 'react';
import {Segment} from 'semantic-ui-react';
import ReactDiffViewer from 'react-diff-viewer';
import numeral from 'numeral';

import * as File from './files';
import * as Panel2 from './panel';
import makeComp from '../../util/profiler';

// TODO: maybe don't import functions from panels?
import * as PanelFileText from './PanelFileText';

const FILE_SIZE_LIMIT = 25 * 1024 * 1024;
const LINE_LENGTH_LIMIT = 5000;
const TOTAL_LINES_LIMIT = 50000;

const inputType = {
  type: 'union' as const,
  members: Object.keys(PanelFileText.EXTENSION_INFO).map(ext => ({
    type: 'row' as const,
    objectType: {
      type: 'file' as const,
      extension: ext,
    },
  })),
};

type PanelFileTextCompareProps = Panel2.PanelProps<typeof inputType>;

const PanelFileTextCompareRenderInner: React.FC<PanelFileTextCompareProps> = makeComp(
  props => {
    const pathsWithMetadata = props.input.data[0];

    const paths = pathsWithMetadata.map(pm => pm.fullPath);
    // TODO: Questionable cast here. We know it's files because of our context
    // check. We could fix this with typescript. The context check itself can
    // reduce the type for the panel, or something like that.
    const contents = File.useFileContent(paths);
    const loading = contents.filter(f => f.loading).length > 0;
    console.log('FILE CONTENTS', pathsWithMetadata, contents, loading);

    const processedResults = useMemo(() => {
      if (loading) {
        return null;
      }

      return contents.map((text, i) =>
        PanelFileText.processTextForDisplay(
          pathsWithMetadata[i].fullPath.path,
          text.contents!
        )
      );
    }, [loading, contents, pathsWithMetadata]);

    if (
      processedResults == null ||
      contents.filter(f => f.loading).length > 0
    ) {
      return <div>loading</div>;
    }

    const truncatedTotalLines = processedResults.some(
      pr => pr.truncatedTotalLines
    );
    const truncatedLineLength = processedResults.some(
      pr => pr.truncatedLineLength
    );
    const data = processedResults.map(pr => pr.text);

    const highlightSyntax = (str: string) => (
      <pre
        style={{display: 'inline'}}
        dangerouslySetInnerHTML={{
          __html: (window.Prism.highlight as any)(
            str || '',
            window.Prism.languages.python
          ),
        }}
      />
    );

    return (
      <div>
        <div>TEXT COMPARE NEW PANEL!</div>
        {truncatedLineLength && (
          <Segment textAlign="center">
            Warning: some lines truncated to {LINE_LENGTH_LIMIT} characters for
            display
          </Segment>
        )}
        {truncatedTotalLines && (
          <Segment textAlign="center">
            Warning: truncated to {TOTAL_LINES_LIMIT} lines for display
          </Segment>
        )}
        {(truncatedLineLength || truncatedTotalLines) &&
          contents[0].contents !== contents[1].contents && (
            <Segment textAlign="center">
              Warning: Files differ but we truncated the content prior to
              diffing. Diff display may not show all mismatches.
            </Segment>
          )}
        <ReactDiffViewer
          oldValue={data[0] ?? undefined}
          newValue={data[1] ?? undefined}
          renderContent={highlightSyntax}
        />
      </div>
    );
  },
  {id: 'PanelFileTextCompareRenderInner'}
);

export const PanelFileTextCompare: React.FC<PanelFileTextCompareProps> = props => {
  const pathsWithMetadata = props.input.data[0];
  console.log('PROPS INPUT DIFF', props.input);

  const largeFiles = pathsWithMetadata.filter(
    pm => (pm.node?.size ?? 0) > FILE_SIZE_LIMIT
  );
  if (largeFiles.length > 0) {
    return (
      <Segment textAlign="center">
        Text view limited to files less than{' '}
        {numeral(FILE_SIZE_LIMIT).format('0.0b')}
      </Segment>
    );
  }

  return <PanelFileTextCompareRenderInner {...props} />;
};

export const Spec: Panel2.PanelSpec = {
  id: 'textdiff',
  displayName: 'Diff',
  Component: PanelFileTextCompare,
  inputType,
};
