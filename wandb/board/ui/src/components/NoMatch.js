import React from 'react';
import {Dimmer, Header, Icon} from 'semantic-ui-react';

const NoMatch = ({model, loading, history}) => (
  <Dimmer active={true} onClickOutside={() => history.goBack()}>
    <Header as="h2" icon inverted>
      <Icon name="battery empty" />
      Not Found!
      <Header.Subheader>
        Couldn't find what you're looking for...
      </Header.Subheader>
    </Header>
  </Dimmer>
);

export default NoMatch;
