import React from 'react';
import * as Panel2 from './panel';

const inputType = 'string' as const;
type PanelStringProps = Panel2.PanelProps<typeof inputType>;

const PanelString: React.FC<PanelStringProps> = props => (
  <div>{props.input.val}</div>
);

export const Spec: Panel2.PanelSpec = {
  id: 'string',
  Component: PanelString,
  inputType,
};
