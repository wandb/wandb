import React from 'react';
import MarkdownIt from 'markdown-it';
import {Item} from 'semantic-ui-react';

const markdown = MarkdownIt('commonmark');

const formatContent = (content, condensed) => {
  if (!content || content.length === 0) return '';
  if (condensed) {
    let parts = content.split(/#+/);
    content = parts[0].length === 0 ? '### ' + parts[1] : parts[0];
    return markdown.render(content);
  } else {
    return markdown.render(content);
  }
};

const Markdown = ({content, condensed}) => (
  <Item.Description
    className={condensed ? '' : 'markdown'}
    dangerouslySetInnerHTML={{__html: formatContent(content, condensed)}}
  />
);
export default Markdown;
