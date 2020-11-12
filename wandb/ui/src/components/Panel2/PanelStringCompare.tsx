import * as _ from 'lodash';
import React from 'react';
import * as Table from './table';
import * as Panel2 from './panel';

const inputType = {
  type: 'row' as const,
  objectType: 'string' as const,
};

type PanelStringCompareProps = Panel2.PanelProps<typeof inputType>;

const PanelStringCompare: React.FC<PanelStringCompareProps> = props => {
  const input = props.input as Table.ResultTable;
  const data: Array<{key: string; val: number}> = _.map(
    input.data[0],
    (v, i) => ({
      key: input.columns[i],
      val: v ?? null,
    })
  );
  return (
    <div>
      {data.map(row => (
        <div>
          {row.key}: {row.val == null ? 'null' : row.val}
        </div>
      ))}
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'string-compare',
  Component: PanelStringCompare,
  inputType,
};
