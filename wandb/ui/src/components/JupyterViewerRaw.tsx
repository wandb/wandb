import React, {useState, useEffect, useMemo} from 'react';
import * as Prism from 'prismjs';
import makeComp from '../util/profiler';
import AU from 'ansi_up';
import './JupyterViewer.css';

function renderableImageType(output: any) {
  return ['image/png', 'image/jpeg', 'image/gif', 'image/bmp'].find(
    type => output.data[type]
  );
}

function renderedImage(output: any, type: string, key: string) {
  return (
    <img
      key={key}
      alt={output.data['text/plain'] || key}
      src={`data:${type};base64,` + output.data[type]}
    />
  );
}

export function processOutputs(cell: any, md: any) {
  const ansiUp = new AU();
  if (cell.outputs == null) {
    console.warn('Empty cell', cell);
    return [];
  }
  return cell.outputs.map((output: any, i: number) => {
    const key = `output${i}`;

    if (output.output_type === 'stream') {
      return (
        <div
          className={`${output.name} stream`}
          key={key}
          dangerouslySetInnerHTML={{
            __html: ansiUp.ansi_to_html(output.text.join('\n')),
          }}
        />
      );
    } else if (output.output_type === 'error') {
      return (
        <div
          className="error"
          key={key}
          dangerouslySetInnerHTML={{
            __html: ansiUp.ansi_to_html(output.traceback.join('\n')),
          }}
        />
      );
    }
    if (output.output_type !== 'display_data') {
      console.warn('Skipping rendering of ', output.output_type);
      return undefined;
    }
    const imageType = renderableImageType(output);
    if (output.data['text/html']) {
      return (
        <div
          className="html"
          key={key}
          dangerouslySetInnerHTML={{
            __html: md.sanitizeHTML(output.data['text/html'].join('')),
          }}
        />
      );
    } else if (imageType) {
      return renderedImage(output, imageType, key);
      // TODO: image/svg+xml, plotly?
    } else if (output.data['text/markdown']) {
      return (
        <div className="markdown" key={key}>
          {md.generateHTML(output.data['text/markdown'].join(''))}
        </div>
      );
    } else if (output.data['text/json']) {
      return (
        <div className="json" key={key}>
          {output.data['text/json'].join('')}
        </div>
      );
    } else if (output.data['text/plain']) {
      return (
        <div className="text" key={key}>
          {output.data['text/plain'].join('')}
        </div>
      );
    } else {
      return undefined;
    }
  });
}
export const JupyterViewer: React.FC<{
  raw: string;
}> = makeComp(
  props => {
    const {raw} = props;
    const [markdownUtil, setMarkdownUtil] = useState<any | null>(null);

    useEffect(() => {
      Prism.highlightAll();
      import('../util/markdown').then(module => setMarkdownUtil(module));
    });

    const result = useMemo(() => {
      let dataInner: any;
      try {
        dataInner = JSON.parse(raw);
      } catch {
        return null;
      }
      const processedOutputsInner: any = {};
      if (dataInner.cells && markdownUtil) {
        dataInner.cells.forEach((cell: any) => {
          processedOutputsInner[cell.execution_count] = processOutputs(
            cell,
            markdownUtil
          );
        });
        return {processedOutputs: processedOutputsInner, data: dataInner};
      } else {
        return null;
      }
    }, [raw, markdownUtil]);
    if (result == null) {
      return <div>Error</div>;
    }
    const {processedOutputs, data} = result;
    return (
      <div className="notebook">
        {data.cells.map((cell: any, i: number) => (
          <div className="cell" key={`cell${i}`}>
            {cell.cell_type === 'code' && (
              <div className="input">
                <div className="gutter">
                  <span>[{cell.execution_count}]: </span>
                </div>
                <div className="source">
                  <pre style={{maxWidth: '100%'}}>
                    <code className="language-python">
                      {cell.source.join('')}
                    </code>
                  </pre>
                </div>
              </div>
            )}
            {cell.cell_type === 'markdown' ? (
              <div
                className="output"
                dangerouslySetInnerHTML={{
                  __html: markdownUtil.generateHTML(cell.source.join('')),
                }}
              />
            ) : (
              <div className="output">
                {processedOutputs![cell.execution_count]}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  },
  {id: 'JupyterViewer'}
);
