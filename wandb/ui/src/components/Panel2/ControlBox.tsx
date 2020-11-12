import React from 'react';
import {Button, Popup} from 'semantic-ui-react';
import makeComp from '../../util/profiler';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import * as Controls from './controlsImage';

const styleOptions: Array<{key: Controls.LineStyle; icon: string}> = [
  {
    key: 'line',
    icon: 'line-solid',
  },
  {
    key: 'dotted',
    icon: 'line-dot',
  },
  {
    key: 'dashed',
    icon: 'line-dash',
  },
];

export const ControlsBoxStyle = makeComp<{
  box: Controls.BoxControlState;
  updateBox: (newBox: Partial<Controls.BoxControlState>) => void;
}>(
  ({box, updateBox}) => {
    const activeMarkOption =
      styleOptions.find(o => o.key === box.lineStyle) || styleOptions[0];

    return (
      <Popup
        offset={-12 as any}
        className="line-style-picker-popup"
        on="click"
        trigger={
          <LegacyWBIcon
            style={{marginLeft: 8}}
            name={activeMarkOption.icon}
            className="line-style-picker"
          />
        }
        content={
          <Button.Group className="line-style-buttons">
            {styleOptions.map(markOption => (
              <Button
                key={markOption.key}
                size="tiny"
                active={markOption.key === box.lineStyle}
                className="wb-icon-button only-icon"
                onClick={() => {
                  updateBox({lineStyle: markOption.key});
                }}>
                <LegacyWBIcon name={markOption.icon} />
              </Button>
            ))}
          </Button.Group>
        }
      />
    );
  },
  {id: 'ControlsBoxStyle'}
);

export const ControlsBox = makeComp<{
  box: Controls.BoxControlState;
  updateBox: (newBox: Partial<Controls.BoxControlState>) => void;
}>(
  ({box, updateBox}) => {
    if (box.type !== 'box') {
      throw new Error('Invalid box control.');
    }
    return <ControlsBoxStyle box={box} updateBox={updateBox} />;
  },
  {id: 'ControlsBox'}
);
