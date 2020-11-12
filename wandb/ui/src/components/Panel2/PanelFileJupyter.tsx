import React from 'react';
import {JupyterViewer} from '../JupyterViewerRaw';

import * as Panel2 from './panel';
import * as File from './files';

const inputType = {
  type: 'file' as const,
  extension: 'ipynb',
};

type PanelJupyterProps = Panel2.PanelProps<typeof inputType>;

export const PanelJupyter: React.FC<PanelJupyterProps> = props => {
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

  return <JupyterViewer raw={content} />;
};

export const Spec: Panel2.PanelSpec = {
  id: 'jupyter',
  Component: PanelJupyter,
  inputType,
};
