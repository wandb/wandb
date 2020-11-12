import * as _ from 'lodash';
import React from 'react';
import {useRef} from 'react';
import {VisualizationSpec} from 'react-vega';
import CustomPanelRenderer from '../Vega3/CustomPanelRenderer';
import * as Table from './table';
import {useGatedValue, useOnScreen} from './hooks';
import * as Panel2 from './panel';

const inputType = {
  type: 'row' as const,
  objectType: 'number' as const,
};

type PanelBarChartProps = Panel2.PanelProps<typeof inputType>;

/* eslint-disable no-template-curly-in-string */

const BAR_CHART: VisualizationSpec = {
  $schema: 'https://vega.github.io/schema/vega-lite/v4.json',
  description: 'A simple bar chart',
  data: {
    name: 'wandb',
  },
  title: '${string:title}',
  mark: {
    type: 'bar',
    tooltip: {
      content: 'data',
    },
  },
  encoding: {
    x: {
      field: '${field:value}',
      type: 'quantitative',
      stack: null,
      axis: {
        title: null,
      },
    },
    y: {
      field: '${field:label}',
      type: 'nominal',
      axis: {
        title: null,
      },
    },
    opacity: {
      value: 0.6,
    },
  },
};

const PanelBarChart: React.FC<PanelBarChartProps> = props => {
  const domRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(domRef!);
  const hasBeenOnScreen = useGatedValue(onScreen, o => o);
  const input = props.input as Table.ResultTable;
  const data: Array<{key: string; val: number}> = _.map(
    input.data[0],
    (v, i) => ({
      key: input.columns[i],
      val: v ?? 0,
    })
  );
  return (
    <div ref={domRef} style={{width: 250, height: 160}}>
      {hasBeenOnScreen && (
        <CustomPanelRenderer
          spec={BAR_CHART}
          loading={props.loading}
          slow={false}
          data={data}
          userSettings={{
            fieldSettings: {label: 'key', value: 'val'},
            stringSettings: {title: ''},
          }}
        />
      )}
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'barchart',
  displayName: 'Bar Chart',
  Component: PanelBarChart,
  inputType,
};
