/* A modified version of semantic's Dropdown, enforces an item limit */
import '../../css/ModifiedDropdown.less';

import _ from 'lodash';
import memoize from 'memoize-one';
import React, {FC, useState, useCallback, useMemo} from 'react';
import {
  Dropdown,
  DropdownItemProps,
  Icon,
  Label,
  StrictDropdownProps,
} from 'semantic-ui-react';
import {RequireSome} from '../../types/base';
import {LabelProps} from 'semantic-ui-react';
import {Omit} from '../../types/base';
import {makePropsAreEqual} from '../../util/shouldUpdate';
import makeComp from '../../util/profiler';

export interface DropdownOption {
  key: string;
  text: string;
  value: string;
}

export type Option = RequireSome<DropdownItemProps, 'value' | 'text'> & {
  content?: DropdownItemProps['content'];
  key?: DropdownItemProps['key'];
};

const ITEM_LIMIT_VALUE = '__item_limit';

const simpleSearch = (options: DropdownItemProps[], query: string) => {
  return _.chain(options)
    .filter(o =>
      _.includes(JSON.stringify(o.text).toLowerCase(), query.toLowerCase())
    )
    .sortBy(o => {
      const valJSON = typeof o.text === 'string' ? `"${query}"` : query;
      return JSON.stringify(o.text).toLowerCase() === valJSON.toLowerCase()
        ? 0
        : 1;
    })
    .value();
};

interface ModifiedDropdownExtraProps {
  style?: any;
  resultLimit?: number;
  itemLimit?: number;

  debounceTime?: number;
  options: Option[];
  optionTransform?(option: Option): Option;
}

type ModifiedDropdownProps = Omit<StrictDropdownProps, 'options'> &
  ModifiedDropdownExtraProps;

const ModifiedDropdown: FC<ModifiedDropdownProps> = makeComp(
  (props: ModifiedDropdownProps) => {
    const {
      itemLimit,
      options: propsOptions,
      optionTransform,
      allowAdditions,
      multiple,
      value,
      search,
      debounceTime,
      onChange,
    } = props;
    const resultLimit = props.resultLimit ?? 100;
    const [searchQuery, setSearchQuery] = useState('');
    const [options, setOptions] = useState(propsOptions);

    const doSearch = useMemo(
      () =>
        _.debounce((query: string) => {
          // in multi-select mode, we have to include all the filtered out selected
          // keys or they won't be rendered
          const currentOptions: Option[] = [];
          if (multiple && Array.isArray(value)) {
            const values = value;
            propsOptions.forEach(opt => {
              if (values.find(v => v === opt.value)) {
                currentOptions.push(opt);
              }
            });
          }

          if (search instanceof Function) {
            setOptions(
              _.concat(currentOptions, search(propsOptions, query) as Option[])
            );
          } else {
            setOptions(
              _.concat(
                currentOptions,
                simpleSearch(propsOptions, query) as Option[]
              )
            );
          }
        }, debounceTime || 400),
      [multiple, propsOptions, search, value, debounceTime]
    );

    const getDisplayOptions = memoize(
      (
        displayOpts: Option[],
        limit: number,
        query: string,
        val: StrictDropdownProps['value']
      ) => {
        const origOpts = displayOpts;
        displayOpts = displayOpts.slice(0, limit);
        if (optionTransform) {
          displayOpts = displayOpts.map(optionTransform);
        }

        let selectedVals = val;
        if (allowAdditions && query !== '') {
          selectedVals = query;
        }

        if (selectedVals != null && (allowAdditions || query === '')) {
          if (!_.isArray(selectedVals)) {
            selectedVals = [selectedVals];
          }
          for (const v of selectedVals) {
            if (!_.find(displayOpts, o => o.value === v)) {
              let option = origOpts.find(o => o.value === v) ?? {
                key: v,
                text: v,
                value: v,
              };
              if (optionTransform) {
                option = optionTransform(option);
              }
              displayOpts.unshift(option);
            }
          }
        }

        if (options.length > resultLimit) {
          displayOpts.push({
            key: ITEM_LIMIT_VALUE,
            text: (
              <span className="hint-text">
                Limited to {resultLimit} items. Refine search to see other
                options.
              </span>
            ),
            value: ITEM_LIMIT_VALUE,
          });
        }

        return displayOpts;
      }
    );

    const itemCount = useCallback(() => {
      let count = 0;
      if (value != null && _.isArray(value)) {
        count = value.length;
      }
      return count;
    }, [value]);

    const atItemLimit = useCallback(() => {
      if (itemLimit == null) {
        return false;
      }
      return itemCount() >= itemLimit;
    }, [itemLimit, itemCount]);

    const displayOptions = getDisplayOptions(
      searchQuery ? options : propsOptions,
      resultLimit,
      searchQuery,
      value
    );

    const renderLabel = (
      item: DropdownItemProps,
      index: number,
      defaultLabelProps: LabelProps
    ) => {
      const onRemove = defaultLabelProps.onRemove!;

      return (
        <Label
          {...defaultLabelProps}
          className="multi-group-label"
          data-test="modified-dropdown-label">
          {item.text}
          <Icon
            onClick={(e: React.MouseEvent<HTMLElement, MouseEvent>) =>
              onRemove(e, defaultLabelProps)
            }
            name="delete"
            data-test="modified-dropdown-label-delete"
          />
        </Label>
      );
    };

    const passProps = {...props};
    delete passProps.itemLimit;
    delete passProps.optionTransform;
    delete passProps.allowAdditions;
    return (
      <Dropdown
        {...passProps}
        options={displayOptions}
        lazyLoad
        selectOnNavigation={false}
        searchQuery={searchQuery}
        search={opts => opts}
        renderLabel={renderLabel}
        onSearchChange={(e, {searchQuery: query}) => {
          if (!atItemLimit() && typeof query === 'string') {
            setSearchQuery(query);
            doSearch(query);
          }
        }}
        onChange={(e, {value: val}) => {
          setSearchQuery('');
          const valCount = _.isArray(val) ? val.length : 0;
          if (valCount < itemCount() || !atItemLimit()) {
            if (onChange && val !== ITEM_LIMIT_VALUE) {
              onChange(e, {value: val});
            }
          }
        }}
      />
    );
  },
  {
    id: 'ModifiedDropdown',
    memo: makePropsAreEqual({
      name: 'ModifiedDropdown',
      deep: ['options'],
      ignore: [],
      ignoreFunctions: true,
      debug: false,
      verbose: true,
    }),
  }
);

export default ModifiedDropdown;
