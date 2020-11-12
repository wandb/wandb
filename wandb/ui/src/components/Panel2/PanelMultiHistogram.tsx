import React from 'react';
import {useMemo, useRef} from 'react';
import {VisualizationSpec} from 'react-vega';
import CustomPanelRenderer from '../Vega3/CustomPanelRenderer';
import {useGatedValue, useOnScreen} from './hooks';
import * as Panel2 from './panel';
import * as Table from './table';

const inputType = {
  type: 'table' as const,
  objectType: 'number' as const,
};

type PanelMultiHistogramProps = Panel2.PanelProps<typeof inputType>;

/* eslint-disable no-template-curly-in-string */

const HISTO_SPEC: VisualizationSpec = {
  $schema: 'https://vega.github.io/schema/vega-lite/v4.json',
  description: 'A simple histogram',
  data: {
    name: 'wandb',
  },
  selection: {
    grid: {
      type: 'interval',
      bind: 'scales',
    },
  },
  title: '${string:title}',
  mark: {type: 'bar', tooltip: {content: 'data'}},
  encoding: {
    x: {
      bin: true,
      type: 'quantitative',
      field: 'value',
      axis: {
        title: null,
      },
    },
    color: {
      field: 'name',
    },
    y: {
      aggregate: 'count',
      stack: null,
      axis: {
        title: null,
      },
    },
    opacity: {value: 0.6},
  },
};

const PanelMultiHistogram: React.FC<PanelMultiHistogramProps> = props => {
  const table = props.input as Table.ResultTable;
  const domRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(domRef);
  const hasBeenOnScreen = useGatedValue(onScreen, o => o);
  const data: Array<{name: string; value: number}> = useMemo(
    () =>
      table.data.flatMap(row =>
        table.columns.map((col, i) => ({
          name: col.replace('.', '_'),
          value: row[i],
        }))
      ),
    [table]
  );
  return (
    <div ref={domRef} style={{width: 250, height: 160}}>
      {hasBeenOnScreen ? (
        <CustomPanelRenderer
          spec={HISTO_SPEC}
          loading={props.loading}
          slow={false}
          data={data}
          userSettings={{fieldSettings: {}, stringSettings: {title: ''}}}
        />
      ) : (
        <div
          style={{
            backgroundColor: '#eee',
            margin: 16,
            width: '100%',
            height: '100%',
          }}
        />
      )}
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'multi-histogram',
  displayName: 'MultiHistogram',
  Component: PanelMultiHistogram,
  inputType,
};
