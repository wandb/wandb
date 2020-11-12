import '../../assets/wb-icons/style.css';

import React from 'react';
import classNames from 'classnames';
import makeComp from '../../util/profiler';

export type WBIconProps = React.ComponentProps<'i'> & {
  name: string;
};

const WBIcon: React.FC<WBIconProps> = makeComp(
  ({name, className, ...standardProps}) => {
    return (
      <i
        {...standardProps}
        className={classNames(`wbic-ic-${name}`, className)}></i>
    );
  },
  {id: 'WBIcon'}
);

export default WBIcon;
