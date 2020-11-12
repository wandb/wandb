import * as _ from 'lodash';
import React from 'react';
import {useEffect} from 'react';
import {Pagination} from 'semantic-ui-react';
import * as Table from './table';
import makeComp from '../../util/profiler';

interface PageControlProps {
  pageParams: {
    offset: number;
    limit: number;
  };
  query: Table.TableQuery;

  updatePageParams(pageParams: {offset: number; limit: number}): void;
}

export const PageControl: React.FC<PageControlProps> = makeComp(
  props => {
    const {query, pageParams, updatePageParams} = props;
    const {offset, limit} = pageParams;
    const tableCountQuery = Table.useTableQueryCount(query);
    const count = tableCountQuery.count;
    const page = Math.ceil(offset / limit);

    useEffect(() => {
      if (page !== 0 && offset >= count) {
        updatePageParams({offset: 0, limit});
      }
    }, [count, limit, offset, page, updatePageParams]);

    return (
      <Pagination
        activePage={page + 1}
        totalPages={Math.ceil(count / limit)}
        onPageChange={(e, data) => {
          const pg = data.activePage;
          if (pg != null && _.isNumber(pg)) {
            updatePageParams({offset: (pg - 1) * limit, limit});
          }
        }}
        size="small"
      />
    );
  },
  {id: 'PageControl'}
);
