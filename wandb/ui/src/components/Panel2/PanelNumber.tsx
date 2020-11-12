import React from 'react';
import * as Panel2 from './panel';

const inputType = 'number' as const;
type PanelNumberProps = Panel2.PanelProps<typeof inputType>;

const PanelNumber: React.FC<PanelNumberProps> = props => (
  <div>{props.input.val.toString()}</div>
);

export const Spec: Panel2.PanelSpec = {
  id: 'number',
  Component: PanelNumber,
  inputType,
};
