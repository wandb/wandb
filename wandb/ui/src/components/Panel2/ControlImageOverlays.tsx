import * as _ from 'lodash';
import React, {useMemo} from 'react';
import makeComp from '../../util/profiler';
import * as Controls from './controlsImage';

import {
  ClassToggle,
  ControlTitle,
  VisibilityToggle,
  SearchInput,
} from './ControlsUtil';

import {ControlsBox} from './ControlBox';
import {ControlsMask} from './ControlMask';
import {fuzzyMatchRegex} from '../../util/fuzzyMatch';
import {DEFAULT_ALL_MASK_CONTROL} from './ImageWithOverlays';
import {ShowMoreContainer} from '../ShowMoreContainer';

const ClassToggles = makeComp<{
  filterString?: string;
  classStates: {[classID: string]: Controls.OverlayClassState};
  classSet: Controls.ClassSetState;
  updateControl: Controls.UpdateControl;
}>(
  ({filterString = '', classStates, classSet, updateControl}) => {
    const filterRegex = useMemo(() => {
      return fuzzyMatchRegex(filterString);
    }, [filterString]);

    const classMatchesFilter = (classId: string) =>
      classSet.classes[classId]?.name.match(filterRegex);

    const classIds = Object.keys(classStates).filter(classMatchesFilter);
    return (
      <ShowMoreContainer iconSize="big">
        {classIds.map(classId => {
          const classState = classStates[classId];
          const classInfo = classSet.classes[classId];
          const {disabled} = classState;

          const toggleClassVisibility = () =>
            updateControl({
              classStates: {
                ...classStates,
                [classId]: {
                  ...classState,
                  disabled: !disabled,
                },
              },
            });

          return (
            <ClassToggle
              key={classId}
              id={classId}
              disabled={disabled}
              name={classInfo.name}
              color={classInfo.color}
              onClick={toggleClassVisibility}
            />
          );
        })}
      </ShowMoreContainer>
    );
  },
  {id: 'ClassToggles'}
);

export const ControlsImageOverlays: React.FC<{
  maskControls?: Controls.OverlayControls;
  classSets?: Controls.ClassSetControls;
  setMaskControls(controlId: string, control: Controls.OverlayState): void;
}> = makeComp(
  props => {
    const {maskControls, classSets, setMaskControls} = props;

    if (maskControls == null || classSets == null) {
      return <div>no controls</div>;
    }

    return (
      <div style={{marginBottom: 10, marginTop: 10}}>
        {_.map(maskControls, (control, controlId) => {
          const {type, name, classSetID, classStates, classSearch} = control;
          const classSet = classSets[classSetID];

          if (classSet == null) {
            throw new Error('invalid');
          }

          const allClass = control.classStates?.all ?? DEFAULT_ALL_MASK_CONTROL;

          const updateControl: Controls.UpdateControl = newControl => {
            const mergedControl = {...control, ...newControl};
            setMaskControls(controlId, mergedControl);
          };

          const toggleControlVisibility = () => {
            updateControl({
              classStates: {
                ...control.classStates,
                all: {
                  ...allClass,
                  disabled: !allClass.disabled,
                },
              },
            });
          };

          const setClassSearch = (newClassSearch: string) => {
            updateControl({classSearch: newClassSearch});
          };

          return (
            <div key={controlId}>
              <VisibilityToggle
                disabled={allClass.disabled}
                onClick={toggleControlVisibility}
              />
              <ControlTitle>
                {name} ({type})
              </ControlTitle>
              {type === 'box' ? (
                <ControlsBox
                  box={control as Controls.BoxControlState}
                  updateBox={updateControl}
                />
              ) : null}
              {type === 'mask' ? (
                <ControlsMask
                  mask={control as Controls.MaskControlState}
                  updateMask={updateControl}
                />
              ) : null}
              <SearchInput value={classSearch} onChange={setClassSearch} />
              <ClassToggles
                filterString={classSearch}
                classStates={classStates}
                classSet={classSet}
                updateControl={updateControl}
              />
            </div>
          );
        })}
      </div>
    );
  },
  {id: 'MaskControls'}
);
