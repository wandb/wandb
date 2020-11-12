import React from 'react';

import * as Panel2 from './panel';
import * as File from './files';
import Loader from '../WandbLoader';
import NoMatch from '../NoMatch';

const inputType = {
  type: 'file' as const,
  extension: 'bag',
};

type PanelWebVizProps = Panel2.PanelProps<typeof inputType>;

const PanelWebViz: React.FC<PanelWebVizProps> = props => {
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
  // analyticsOK is set by index.html
  const enableTelemetryString = !(window as any).analyticsOK
    ? ''
    : '&telemetry=1';

  return (
    <iframe
      style={{width: '100%', height: '100%', border: 'none'}}
      title="WebViz preview"
      src={`/webviz/index.html?remote-bag-url=${encodeURIComponent(
        directURL
      )}${enableTelemetryString}`}
    />
    // Webviz supports comparison but it's broken. I asked in the Slack
    // forum and they said "Yikes, that's a pretty serious bug. I'll look into it."
    // It's possible it's fixed in a newer version.
    // return (
    //   <iframe
    //     style={{width: '100%', height: '100%', border: 'none'}}
    //     title="WebViz preview"
    //     src={`/webviz/index.html?remote-bag-url=${encodeURIComponent(
    //       directURL1
    //     )}${
    //       directUrl2 != null
    //         ? '&remote-bag-url-2=' + encodeURIComponent(directUrl2)
    //         : ''
    //     }${enableTelemetryString}`}
    //   />
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'web-viz',
  Component: PanelWebViz,
  inputType,
};
