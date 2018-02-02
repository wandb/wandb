import React from 'react';
import {Button, Popup} from 'semantic-ui-react';

export default function HelpIcon({content, text}) {
  return (
    <Popup
      trigger={
        <Button
          circular
          size="mini"
          icon="help"
          color="blue"
          style={{
            marginLeft: 4,
            padding: 4,
            position: 'relative',
            top: -1,
          }}
        />
      }
      content={content || text}
    />
  );
}
