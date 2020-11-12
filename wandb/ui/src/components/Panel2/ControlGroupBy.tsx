import React from 'react';
import * as Table from './table';
import ModifiedDropdown from '../elements/ModifiedDropdown';
import {Button, Popup} from 'semantic-ui-react';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import makeComp from '../../util/profiler';

interface GroupByControlProps {
  keys: string[];
  groupBy: Table.GroupBy;
  setGroupBy(newGroupBy: Table.GroupBy): void;
}

export const GroupByControl: React.FC<GroupByControlProps> = makeComp(
  props => {
    const {keys, groupBy, setGroupBy} = props;
    const options = [
      {key: 'none', value: '', text: ''},
      ...keys.map(k => ({key: k, value: k, text: k})),
    ];
    const curKey = groupBy[0];
    return (
      <Popup
        basic
        className="wb-table-action-popup"
        on="click"
        position="bottom left"
        trigger={
          <Button
            data-test="sort-popup"
            size="tiny"
            className={'wb-icon-button table-group-button'}>
            <LegacyWBIcon name="group-runs" title="Group" />
            Group
          </Button>
        }
        content={
          <div style={{display: 'flex'}}>
            <ModifiedDropdown
              selection
              search
              options={options}
              value={curKey}
              onChange={(e, {value}) => {
                if (value != null && value !== '') {
                  setGroupBy([value as string]);
                } else {
                  setGroupBy([]);
                }
              }}
            />
          </div>
        }
        popperModifiers={{
          preventOverflow: {enabled: false},
          flip: {enabled: false},
        }}
      />
    );
  },
  {id: 'SortControl'}
);
