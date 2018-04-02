import React from 'react';
import {NavLink} from 'react-router-dom';
import {Button, Header} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import numeral from 'numeral';
import Breadcrumbs from '../components/Breadcrumbs';

class ModelHeader extends React.Component {
  render() {
    var {model, user, condensed} = this.props;
    const hasFiles =
      model.bucket && model.bucket.files && model.bucket.files.edges.length > 0;
    return (
      <div>
        <Header>
          <Breadcrumbs
            style={{marginRight: 12}}
            entity={model.entityName}
            model={model.name}
          />
          <Button.Group basic size="small">
            {!condensed &&
              user && (
                <NavLink to={`/${model.entityName}/${model.name}/edit`}>
                  <Button icon="edit" />
                  {/* Empty span so that Button doesn't match an :only-child css rule
                  that screws up rendering in the header */}
                  <span />
                </NavLink>
              )}
          </Button.Group>
        </Header>
        {!condensed && (
          <div style={{color: 'gray'}}>
            Updated{' '}
            <TimeAgo date={(model.bucket.createdAt || model.createdAt) + 'Z'} />
            {hasFiles &&
              `Avg Size ${numeral(
                model.bucket.files.edges
                  .map(e => parseInt(e.node.sizeBytes, 10))
                  .reduce((a, b) => a + b, 0),
              ).format('0.0b')} `}{' '}
          </div>
        )}
      </div>
    );
  }
}

export default ModelHeader;
