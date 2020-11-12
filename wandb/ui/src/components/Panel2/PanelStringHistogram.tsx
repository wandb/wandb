import * as _ from 'lodash';
import React from 'react';
import {useMemo, useRef} from 'react';
import {VisualizationSpec} from 'react-vega';
import CustomPanelRenderer from '../Vega3/CustomPanelRenderer';
import {useGatedValue, useOnScreen} from './hooks';
import * as Panel2 from './panel';
import * as Table from './table';

const inputType = {
  type: 'column' as const,
  objectType: 'string' as const,
};

type PanelStringHistogramProps = Panel2.PanelProps<typeof inputType>;

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
    y: {
      type: 'nominal',
      field: '${field:value}',
      axis: {
        title: null,
      },
    },
    x: {
      aggregate: 'count',
      stack: null,
      axis: {
        title: null,
      },
    },
    opacity: {value: 0.6},
  },
};

const PanelStringHistogram: React.FC<PanelStringHistogramProps> = props => {
  const table = props.input as Table.ResultTable;
  const domRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(domRef);
  const hasBeenOnScreen = useGatedValue(onScreen, o => o);
  const yAxis = table.columns[0];
  const data: Array<{[key: string]: number}> = useMemo(
    () =>
      table.data.map(row =>
        _.fromPairs(
          table.columns.map((col, i) => [col.replace('.', '_'), row[i]])
        )
      ),
    [table]
  );
  const fieldSettings: {[key: string]: string} =
    yAxis != null ? {value: yAxis.replace('.', '_')} : {};
  return (
    <div ref={domRef} style={{width: 250, height: 160}}>
      {hasBeenOnScreen ? (
        <CustomPanelRenderer
          spec={HISTO_SPEC}
          loading={props.loading}
          slow={false}
          data={data}
          userSettings={{fieldSettings, stringSettings: {title: ''}}}
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
  id: 'string-histogram',
  Component: PanelStringHistogram,
  inputType,
};
