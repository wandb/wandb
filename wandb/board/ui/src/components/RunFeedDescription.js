import React from 'react';
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
      subgroupCount,
      runCount,
      subgroupClick,
      runsClick,
      subgroupOpen,
      runsOpen,
    } = this.props;
    return (
      <Table.Cell
        rowSpan={this.props.rowSpan}
        className="overview"
        key="Description">
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
                  {subgroupCount && (
                    <a onClick={() => subgroupClick && subgroupClick()}>
                      <Icon
                        rotated={!subgroupOpen && 'counterclockwise'}
                        name="dropdown"
                      />
                      {subgroupCount} Subgroups
                    </a>
                  )}
                  {runCount && (
                    <a onClick={() => runsClick && runsClick()}>
                      <Icon
                        rotated={!runsOpen && 'counterclockwise'}
                        name="dropdown"
                      />
                      {runCount} Runs
                    </a>
                  )}
                </Item.Extra>
              </Item.Content>
            </Item>
          </Item.Group>
        </div>
      </Table.Cell>
    );
  }
}
