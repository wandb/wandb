import * as S from './ControlFilter.styles';

import React, {useCallback, useState} from 'react';
import * as Table from './table';
import {Button, Modal} from 'semantic-ui-react';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import makeComp from '../../util/profiler';
import {
  assertMongoFilterIsSupported,
  EXAMPLE_FILTER,
  SUPPORTED_MONGO_AGG_OPS,
} from './table';
import {CodeBlock, CopyableCode} from '../Code';
import {JSONize} from '../../util/json';
import {isDev} from '../../config';
import {TargetBlank} from '../../util/links';

const PLACEHOLDER = `{
  $and: [
    {$gt: ['$loss', 0.3]},
    {$eq: ['$class', 'cat']}
  ]
}
`;

interface FilterControlProps {
  filter?: Table.MongoFilter;
  setFilter(newFilter: Table.MongoFilter): void;
}

export const FilterControl: React.FC<FilterControlProps> = makeComp(
  ({filter, setFilter}) => {
    const [open, setOpen] = useState(false);
    const [helpModalOpen, setHelpModalOpen] = useState(false);
    const [value, setValue] = useState(
      filter != null ? JSON.stringify(filter) : ''
    );
    const [error, setError] = useState('');

    const openPopup = useCallback(() => setOpen(true), []);
    const closePopup = useCallback(() => {
      try {
        const newFilter = value !== '' ? JSON.parse(JSONize(value)) : undefined;
        assertMongoFilterIsSupported(newFilter);
        setFilter(newFilter);
        setError('');
        setOpen(false);
      } catch (err) {
        if (isDev()) {
          console.group('INVALID MONGO FILTER');
          console.log(value);
          console.log(`Converted to JSON:\n${JSONize(value)}`);
          console.error(err);
          console.groupEnd();
        }
        setError('Query is invalid');
      }
    }, [value, setFilter]);

    const openHelpModal = useCallback(() => {
      setOpen(false);
      setHelpModalOpen(true);
    }, []);
    const closeHelpModal = useCallback(() => setHelpModalOpen(false), []);

    const setValueFromEvent = useCallback(e => setValue(e.target.value), []);

    return (
      <>
        <S.Popup
          basic
          open={open}
          onOpen={openPopup}
          onClose={closePopup}
          className="wb-table-action-popup"
          on="click"
          position="bottom left"
          trigger={
            <Button
              data-test="filter-popup"
              size="tiny"
              className={'wb-icon-button table-filter-button'}>
              <LegacyWBIcon name="filter" title={'Filter'} />
              Filter
            </Button>
          }
          popperModifiers={{
            preventOverflow: {enabled: false},
            flip: {enabled: false},
          }}>
          {error !== '' && <S.Error>{error}</S.Error>}
          <S.PopupContent>
            <S.Textarea
              placeholder={PLACEHOLDER}
              value={value}
              onChange={setValueFromEvent}
            />
            <S.OpenHelpLink onClick={openHelpModal}>
              What is this?
            </S.OpenHelpLink>
          </S.PopupContent>
        </S.Popup>
        <FilterControlHelpModal open={helpModalOpen} onClose={closeHelpModal} />
      </>
    );
  },
  {id: 'FilterControl', memo: true}
);

interface FilterControlHelpModalProps {
  open: boolean;
  onClose(): void;
}

const FilterControlHelpModal: React.FC<FilterControlHelpModalProps> = makeComp(
  ({open, onClose}) => {
    return (
      <S.HelpModal open={open} onClose={onClose}>
        <Modal.Header>HALP</Modal.Header>
        <Modal.Content>
          <S.HelpText>
            Filter your dataset viz items using the{' '}
            <TargetBlank href="https://docs.mongodb.com/manual/meta/aggregation-quick-reference/">
              MongoDB aggregation language
            </TargetBlank>
            .
          </S.HelpText>
          <S.HelpText>
            We currently only support the following aggregation operators:
            <S.HelpList>
              {SUPPORTED_MONGO_AGG_OPS.map(op => (
                <S.HelpListItem key={op}>{op}</S.HelpListItem>
              ))}
            </S.HelpList>
          </S.HelpText>
          <S.HelpText>
            For example, to find all examples which have at least 4 boxes with
            `class_id` 1:
          </S.HelpText>
          <CodeBlock>
            <CopyableCode>{EXAMPLE_FILTER}</CopyableCode>
          </CodeBlock>
        </Modal.Content>
      </S.HelpModal>
    );
  },
  {id: 'FilterControlHelpModal', memo: true}
);
