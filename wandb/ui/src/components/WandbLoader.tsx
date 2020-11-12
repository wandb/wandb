/* This used to be the custom bouncing dots loader. But that broke
 * with an upgrade of react-spring, so we've switched back to the semantic loader.
 * The react-spring version also used 100% cpu, we should use an animated gif
 * instead if we want a custom loader */
import React from 'react';
import {Loader} from 'semantic-ui-react';
import makeComp from '../util/profiler';

interface WandbLoaderProps {
  className?: string;
}

const WandbLoader = makeComp(
  ({className}: WandbLoaderProps) => {
    return <Loader active size="huge" className={className} />;
  },
  {id: 'WandbLoader'}
);

export default WandbLoader;
