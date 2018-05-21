import React from 'react';
import {Button, Popup} from 'semantic-ui-react';

export default function HelpIcon({content, text, style, color, size, preText}) {
  return (
    <Popup
      trigger={
        <span style={{color: color || 'blue'}}>
          {preText}{' '}
          <Button
            circular
            size="mini"
            icon="help"
            color={color || 'blue'}
            style={Object.assign(
              {
                backgroundColor: color || 'blue',
                marginLeft: size === 'small' ? 1 : 4,
                padding: size === 'small' ? 2 : 4,
                position: 'relative',
                top: -1,
              },
              style
            )}
          />
        </span>
      }
      content={content || text}
    />
  );
}
