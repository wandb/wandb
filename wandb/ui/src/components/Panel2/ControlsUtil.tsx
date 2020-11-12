import React from 'react';
import styled from 'styled-components';
import makeComp from '../../util/profiler';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import Input from '../Input';

// import '../PanelMediaBrowser.less';

export const SearchInput = makeComp<{
  value: string;
  onChange: (newValue: string) => void;
}>(
  ({value, onChange}) => {
    return (
      <Input
        className="mask-search__input"
        icon={
          <LegacyWBIcon
            style={{cursor: 'pointer'}}
            name="search"></LegacyWBIcon>
        }
        iconPosition="left"
        value={value}
        onChange={(_, {value: searchString}) => onChange(searchString)}
      />
    );
  },
  {id: 'ControlSearchInput'}
);

export const VisibilityToggle: React.FC<{
  disabled?: boolean;
  onClick?: any;
}> = ({disabled, onClick}) => {
  return (
    <LegacyWBIcon
      style={{cursor: 'pointer'}}
      onClick={onClick}
      size="large"
      name={disabled ? 'hide' : 'show'}
    />
  );
};

export const ClassToggle: React.FC<{
  id: string | number;
  name: string;
  disabled: boolean;
  color: string;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  showId?: boolean;
}> = makeComp(
  ({onClick, disabled, color, id, name, showId = false}) => {
    return (
      <div
        onClick={onClick}
        className="mask-control__button"
        style={{
          margin: 2,
          borderWidth: 0,
          background: disabled ? '#888' : color,
        }}>
        {name} {showId ? <span>({id})</span> : null}
      </div>
    );
  },
  {id: 'ClassToggleButton'}
);

export const ControlTitle = styled.span`
  font-weight: bold;
`;
