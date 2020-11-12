import React from 'react';
import * as Table from './table';
import ModifiedDropdown from '../elements/ModifiedDropdown';
import {Button, Popup} from 'semantic-ui-react';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import makeComp from '../../util/profiler';

interface SortControlProps {
  keys: string[];
  sort: Table.Sort;
  setSort(newSort: Table.Sort): void;
}

export const SortControl: React.FC<SortControlProps> = makeComp(
  props => {
    const {keys, sort, setSort} = props;
    const options = keys.map(k => ({key: k, value: k, text: k}));
    const curKey = sort[0]?.key ?? undefined;
    const curAscending = sort[0]?.ascending ?? true;
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
            className={'wb-icon-button table-sort-button'}>
            <LegacyWBIcon name="sort" title={'Sort'} />
            Sort
          </Button>
        }
        content={
          <div style={{display: 'flex'}}>
            <ModifiedDropdown
              selection
              search
              options={options}
              value={curKey}
              onChange={(e, {value}) =>
                setSort([{key: value as string, ascending: true}])
              }
            />
            <Button
              data-test="sort-order"
              style={{marginLeft: 8}}
              icon={`sort amount ${curAscending ? 'up' : 'down'}`}
              onClick={() => setSort([{key: curKey, ascending: !curAscending}])}
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
