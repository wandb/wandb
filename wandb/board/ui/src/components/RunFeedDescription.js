import React from 'react';
import {NavLink} from 'react-router-dom';
import {Icon, Item, Image, Table} from 'semantic-ui-react';
import {stateToIcon} from '../util/runhelpers.js';
import Tags from '../components/Tags';
import HelpIcon from '../components/HelpIcon';

export default class RunFeedDescription extends React.Component {
  renderRunName() {
    const {run} = this.props;
    return (
      <span style={{whiteSpace: 'nowrap'}}>
        {run.description || run.name
          ? (run.description || run.name).split('\n')[0]
          : ''}{' '}
        {stateToIcon(run.state)}
      </span>
    );
  }

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
                  {subgroupCount || runCount ? (
                    this.renderRunName()
                  ) : (
                    <NavLink
                      to={`/${project.entityName}/${project.name}/runs/${
                        run.name
                      }`}>
                      {this.renderRunName()}
                    </NavLink>
                  )}
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
                        rotated={!subgroupOpen ? 'counterclockwise' : undefined}
                        name="dropdown"
                      />
                      {subgroupCount} Subgroups
                    </a>
                  )}
                  {runCount && (
                    <a onClick={() => runsClick && runsClick()}>
                      <Icon
                        rotated={!runsOpen ? 'counterclockwise' : undefined}
                        name="dropdown"
                      />
                      {runCount} Runs
                    </a>
                  )}
                  {runCount === 300 && (
                    <span style={{color: 'orange', fontStyle: 'italic'}}>
                      <HelpIcon
                        preText="limited!"
                        color="#ecbb33"
                        size="small"
                        text="Group results are currently limited to 300 runs per group. Please contact team@wandb.com if you'd like a higher limit."
                      />
                    </span>
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
