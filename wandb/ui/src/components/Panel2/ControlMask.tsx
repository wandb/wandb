import React from 'react';
import makeComp from '../../util/profiler';
import * as Controls from './controlsImage';

export const ControlsMask = makeComp<{
  mask: Controls.MaskControlState;
  updateMask: (newMask: Partial<Controls.MaskControlState>) => void;
}>(
  ({mask, updateMask}) => {
    if (mask.type !== 'mask') {
      throw new Error('Invalid mask control.');
    }
    return <span></span>;
  },
  {id: 'ControlsMask'}
);
