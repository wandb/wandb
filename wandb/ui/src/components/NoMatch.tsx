import React from 'react';
import {Header, Button} from 'semantic-ui-react';
import {NavLink} from 'react-router-dom';
import '../css/NoMatch.less';
import makeComp from '../util/profiler';

const NoMatch = makeComp(
  () => {
    return (
      <div className="nomatch">
        <Header>404</Header>
        <p>Looks like you stumbled on an empty page.</p>
        <NavLink to={`/`}>
          <Button primary>Home</Button>
        </NavLink>
      </div>
    );
  },
  {id: 'NoMatch'}
);

export default NoMatch;
