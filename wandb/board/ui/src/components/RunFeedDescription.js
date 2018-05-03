import React from 'react';
import ContentLoader from 'react-content-loader';
import {NavLink} from 'react-router-dom';
import {Icon, Item, Image, Table} from 'semantic-ui-react';
import {stateToIcon} from '../util/runhelpers.js';
import Tags from '../components/Tags';

export default class RunFeedDescription extends React.Component {
  render() {
    const {
      loading,
      project,
      run,
      addFilter,
      subgroupClick,
      runsClick,
    } = this.props;
    return (
      <Table.Cell
        rowSpan={this.props.rowSpan}
        className="overview"
        key="Description">
        {loading && (
          <ContentLoader
            style={{height: 43}}
            height={63}
            width={350}
            speed={2}
            primaryColor={'#f3f3f3'}
            secondaryColor={'#e3e3e3'}>
            <circle cx="32" cy="32" r="30" />
            <rect x="75" y="13" rx="4" ry="4" width="270" height="13" />
            <rect x="75" y="40" rx="4" ry="4" width="50" height="8" />
          </ContentLoader>
        )}
        {!loading && (
          <div>
            <Item.Group>
              <Item>
                <Item.Image size="tiny" style={{width: 40}}>
                  <Image
                    src={run.user && run.user.photoUrl}
                    size="mini"
                    style={{borderRadius: '500rem'}}
                  />
                </Item.Image>
                <Item.Content>
                  <Item.Header>
                    <NavLink
                      to={`/${project.entityName}/${project.name}/runs/${
                        run.name
                      }`}>
                      {run.description || run.name
                        ? (run.description || run.name).split('\n')[0]
                        : ''}{' '}
                      {stateToIcon(run.state)}
                    </NavLink>
                  </Item.Header>
                  <Item.Extra style={{marginTop: 0}}>
                    <strong>{run.user && run.user.username}</strong>
                    {/* run.host && `on ${run.host} ` */}
                    {/*run.fileCount + ' files saved' NOTE: to add this back, add fileCount back to RUNS_QUERY*/}
                    <Tags
                      tags={run.tags}
                      addFilter={tag =>
                        addFilter(
                          'filter',
                          {section: 'tags', name: tag},
                          '=',
                          true
                        )
                      }
                    />
                    {run.subgroupCount && (
                      <a onClick={() => subgroupClick && subgroupClick()}>
                        <Icon
                          rotated={
                            this.props.subgroupsClosed && 'counterclockwise'
                          }
                          name="dropdown"
                        />
                        {run.subgroupCount} Subgroups
                      </a>
                    )}
                    {run.runCount && (
                      <a onClick={() => runsClick && runsClick()}>
                        <Icon
                          rotated={this.props.runsClosed && 'counterclockwise'}
                          name="dropdown"
                        />
                        {run.runCount} Runs
                      </a>
                    )}
                  </Item.Extra>
                </Item.Content>
              </Item>
            </Item.Group>
          </div>
        )}
      </Table.Cell>
    );
  }
}
