import React from 'react';
import makeComp from '../../util/profiler';

const PanelError = makeComp(
  (props: {message: React.ReactChild; className?: string}) => {
    return (
      <div className={`panel-error ${props.className || ''}`}>
        {props.message}
      </div>
    );
  },
  {id: 'PanelError'}
);
export default PanelError;
