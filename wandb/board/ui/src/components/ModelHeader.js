import React from 'react';
import {NavLink} from 'react-router-dom';
import {Button, Header} from 'semantic-ui-react';
import TimeAgo from 'react-timeago';
import numeral from 'numeral';
import Breadcrumbs from '../components/Breadcrumbs';

class ModelHeader extends React.Component {
  render() {
    var {project, user, condensed} = this.props;
    const hasFiles =
      project.run && project.run.files && project.run.files.edges.length > 0;
    return (
      <div>
        <Header>
          <Breadcrumbs
            style={{marginRight: 12}}
            entity={project.entityName}
            model={project.name}
          />
          <Button.Group basic size="small">
            {!condensed &&
              user && (
                <NavLink to={`/${project.entityName}/${project.name}/edit`}>
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
            <TimeAgo
              date={
                ((project.run && project.run.createdAt) || project.createdAt) +
                'Z'
              }
            />
            {hasFiles &&
              `Avg Size ${numeral(
                project.run.files.edges
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
