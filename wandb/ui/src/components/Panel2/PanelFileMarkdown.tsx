import React from 'react';
import Markdown from '../Markdown';

import * as Panel2 from './panel';
import * as File from './files';

const inputType = {
  type: 'union' as const,
  members: ['md', 'markdown'].map(extension => ({
    type: 'file' as const,
    extension,
  })),
};

type PanelFileMarkdownProps = Panel2.PanelProps<typeof inputType>;

const PanelFileMarkdown: React.FC<PanelFileMarkdownProps> = props => {
  const pathObj = props.input;
  const path = pathObj.val.fullPath;
  const contents = File.useFileContent([path])[0];
  if (contents.loading) {
    return <div>loading</div>;
  }

  const content = contents.contents;
  if (content == null) {
    throw new Error('invalid');
  }

  return (
    <div
      style={{
        background: 'white',
        border: '1px solid #eee',
        padding: 16,
      }}>
      <div>NEW PANEL!</div>
      <pre
        style={{
          maxWidth: '100%',
          overflowX: 'auto',
          textOverflow: 'ellipsis',
        }}>
        <Markdown condensed={false} content={content} />
      </pre>
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'markdown',
  Component: PanelFileMarkdown,
  inputType,
};
