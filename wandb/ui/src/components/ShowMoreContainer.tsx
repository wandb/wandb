import * as React from 'react';
import {useState} from 'react';
import LegacyWBIcon from './elements/LegacyWBIcon';
import {IconSizeProp} from 'semantic-ui-react/dist/commonjs/elements/Icon/Icon';
import makeComp from '../util/profiler';

export const ShowMoreContainer = makeComp(
  (props: {iconSize?: IconSizeProp; children: JSX.Element[]}) => {
    const [open, setOpen] = useState<boolean>(false);
    const iconSize = props.iconSize;

    const iconProps = {size: iconSize, onClick: () => setOpen(!open)};

    return (
      <div style={{display: 'flex', width: 600}}>
        <LegacyWBIcon
          {...iconProps}
          name="next"
          style={{
            cursor: 'pointer',
            transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          }}
          className="open"
        />
        <div
          style={{
            maxHeight: open ? undefined : 34,
            overflow: 'hidden',
          }}>
          {props.children}
        </div>
      </div>
    );
  },
  {id: 'ShowMoreContainer'}
);
