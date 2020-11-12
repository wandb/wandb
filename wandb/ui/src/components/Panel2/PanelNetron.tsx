import React from 'react';

import * as Panel2 from './panel';
import * as File from './files';
import NoMatch from '../NoMatch';
import Loader from '../WandbLoader';
import * as NetronUtils from '../../util/netron';

const inputType = {
  type: 'union' as const,
  members: NetronUtils.EXTENSIONS.map(e => ({
    type: 'file' as const,
    extension: e.slice(1), // remove initial '.'
  })),
};
type PanelNetronProps = Panel2.PanelProps<typeof inputType>;

const PanelNetron: React.FC<PanelNetronProps> = props => {
  const pathObj = props.input;
  const path = pathObj.val.fullPath;
  const directURLQuery = File.useFileDirectUrl([path])[0];
  // const query = useSingleFileQuery(props);
  if (directURLQuery.loading) {
    return <Loader />;
  }
  const directURL = directURLQuery.directUrl;
  if (directURL == null) {
    return <NoMatch />;
  }
  const name =
    path.artifactSequenceName + ':' + path.artifactCommitHash + '/' + path.path;
  // analyticsOK is set by index.html
  const enableTelemetryString = !(window as any).analyticsOK
    ? ''
    : '&telemetry=1';
  return (
    <iframe
      style={{width: '100%', height: '100%', border: 'none'}}
      title="Netron preview"
      src={`/netron/index.html?url=${encodeURIComponent(
        directURL
      )}&identifier=${encodeURIComponent(name)}${enableTelemetryString}`}
    />
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'netron',
  Component: PanelNetron,
  inputType,
};
