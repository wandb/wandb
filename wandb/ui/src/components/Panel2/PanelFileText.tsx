import React from 'react';
import {useEffect, useMemo, useRef} from 'react';
import {Segment} from 'semantic-ui-react';
import Prism from 'prismjs';
import numeral from 'numeral';

import * as File from './files';
import * as Panel2 from './panel';
import * as Path from '../../util/path';
import makeComp from '../../util/profiler';

export const EXTENSION_INFO: {[key: string]: string} = {
  log: 'text',
  text: 'text',
  txt: 'text',
  markdown: 'markdown',
  md: 'markdown',
  patch: 'diff',
  ipynb: 'python',
  py: 'python',
  yaml: 'yaml',
  xml: 'xml',
  html: 'html',
  htm: 'html',
  json: 'json',
  css: 'css',
  js: 'js',
};

const inputType = {
  type: 'union' as const,
  members: Object.keys(EXTENSION_INFO).map(ext => ({
    type: 'file' as const,
    extension: ext,
  })),
};

type PanelFileTextProps = Panel2.PanelProps<typeof inputType>;

const FILE_SIZE_LIMIT = 25 * 1024 * 1024;
const LINE_LENGTH_LIMIT = 5000;
const TOTAL_LINES_LIMIT = 50000;

export const processTextForDisplay = (fileName: string, text: string) => {
  let lines = text.split('\n');
  let truncatedLineLength = false;
  let truncatedTotalLines = false;

  // Pretty-print JSON
  if (
    (fileName.endsWith('json') && lines.length === 1) ||
    (lines.length === 2 && lines[1] === '')
  ) {
    try {
      const parsed = JSON.parse(lines[0]);
      lines = JSON.stringify(parsed, undefined, 2).split('\n');
    } catch {
      // ok
    }
  }

  // Truncate long lines
  lines = lines.map(line => {
    if (line.length > LINE_LENGTH_LIMIT) {
      truncatedLineLength = true;
      return (
        line.slice(0, LINE_LENGTH_LIMIT) +
        ` ... (line truncated to ${LINE_LENGTH_LIMIT} characters)`
      );
    } else {
      return line;
    }
  });

  if (lines.length > TOTAL_LINES_LIMIT) {
    truncatedTotalLines = true;
    lines = [
      ...lines.slice(0, TOTAL_LINES_LIMIT),
      '...',
      `(truncated to ${TOTAL_LINES_LIMIT} lines)`,
    ];
  }

  return {
    text: lines.join('\n'),
    truncatedLineLength,
    truncatedTotalLines,
  };
};

const PanelFileTextRenderInner: React.FC<PanelFileTextProps> = makeComp(
  props => {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
      if (ref.current != null) {
        Prism.highlightElement(ref.current);
      }
    });

    const pathObj = props.input;
    const path = pathObj.val.fullPath;
    const contents = File.useFileContent([path])[0];
    const loading = contents.loading;

    const processedResults = useMemo(() => {
      if (loading) {
        return null;
      }
      return processTextForDisplay(path.path, contents.contents!);
    }, [loading, path.path, contents]);

    if (loading) {
      return <div>loading</div>;
    }

    const truncatedTotalLines = processedResults?.truncatedLineLength;
    const truncatedLineLength = processedResults?.truncatedTotalLines;
    const text = processedResults?.text;
    const language = languageFromFileName(path.path);

    return (
      <div>
        <div>NEW PANEL!</div>
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
        <div
          style={{
            background: 'white',
            border: '1px solid #eee',
            padding: 16,
          }}>
          <pre
            style={{
              maxWidth: '100%',
              overflowX: 'hidden',
              textOverflow: 'ellipsis',
            }}>
            <code
              ref={ref}
              className={language != null ? `language-${language}` : undefined}>
              {text}
            </code>
          </pre>
        </div>
      </div>
    );
  },
  {id: 'PanelFileTextRenderInner'}
);

export const PanelFileText: React.FC<PanelFileTextProps> = props => {
  const pathWithMetadata = props.input.val;

  if ((pathWithMetadata.node?.size ?? 0) > FILE_SIZE_LIMIT) {
    return (
      <Segment textAlign="center">
        Text view limited to files less than{' '}
        {numeral(FILE_SIZE_LIMIT).format('0.0b')}
      </Segment>
    );
  }

  return <PanelFileTextRenderInner {...props} />;
};

// TODO: we can have better types here
function languageFromFileName(fileName: string): string | null {
  const extension = Path.extension(fileName);
  return EXTENSION_INFO[extension] ?? null;
}

export const Spec: Panel2.PanelSpec = {
  id: 'text',
  Component: PanelFileText,
  inputType,
};
