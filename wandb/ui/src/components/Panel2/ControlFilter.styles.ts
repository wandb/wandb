import styled from 'styled-components';
import {Popup as SemanticPopup, Modal} from 'semantic-ui-react';
import {Static} from '../Code';

export const Popup = styled(SemanticPopup)`
  &&&&& {
    padding: 0;
  }
`;

export const Error = styled.div`
  background-color: #fff6f6;
  color: #9f3a38;
  padding: 16px;
`;

export const PopupContent = styled.div`
  padding: 16px;
`;

export const Textarea = styled.textarea`
  width: 500px;
  height: 300px;
`;

export const OpenHelpLink = styled.div`
  margin-top: 8px;
  color: #007faf;
  cursor: pointer;
  &:hover {
    color: #00729e;
  }
`;

export const HelpModal = styled(Modal)`
  max-width: 600px;
`;

export const HelpText = styled.div`
  &:not(:first-child) {
    margin-top: 16px;
  }
`;

export const HelpList = styled.ul`
  padding-left: 24px;
  margin-top: 8px;
  margin-bottom: 0;
`;

export const HelpListItem = styled.li``;

export const ExampleFilter = styled(Static)`
  &&&&& {
    white-space: pre;
    background-color: #2a2a2a;
    margin-top: 16px;
  }
`;
