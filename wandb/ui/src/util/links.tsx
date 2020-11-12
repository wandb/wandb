import _ from 'lodash';
import React from 'react';
import makeComp from './profiler';

const URL_REGEXP = /https?:\/\/[^\s]+/g;
const MD_LINK_REGEXP = /\[[^\]]+\]\(https?:\/\/[^)\s]+\)/g;

// Given a string that might have URLs in it, returns an array
// where each element is a portion of the original string or a
// JSX element containing one of the links, with the original ordering
// preserved.
// For example, this input: "See my website at http://mywebsite.com and leave a comment!"
// would yield the following output: ['See my website at ', <a href.../>, ' and leave a comment!']
export function linkify(
  text: string,
  props: JSX.IntrinsicElements['a']
): Array<string | JSX.Element> {
  const parts = linkifyWithRegex(text, props, MD_LINK_REGEXP, (m, i) => {
    const descEnd = m.indexOf(']');
    const desc = m.slice(1, descEnd);
    const href = m.slice(descEnd + 2, m.length - 1);
    return (
      <a key={`${href}-${i}`} href={href} {...props}>
        {desc}
      </a>
    );
  });
  return _.flatten(
    parts.map(p => {
      if (typeof p !== 'string') {
        return p;
      }
      return linkifyWithRegex(p, props, URL_REGEXP, (m, i) => (
        <a key={`${m}-${i}`} href={m} {...props}>
          {m}
        </a>
      ));
    })
  );
}

function linkifyWithRegex(
  text: string,
  props: JSX.IntrinsicElements['a'],
  r: RegExp,
  getLinkFromMatch: (m: string, i: number) => JSX.Element
): Array<string | JSX.Element> {
  const matches = text.match(r) || [];
  const elems: Array<string | JSX.Element> = [text];
  matches.forEach((match, i) => {
    const remainingStr = elems.pop();
    if (remainingStr == null || !_.isString(remainingStr)) {
      // This is mostly a typeguard. This shouldn't happen.
      throw new Error('Exception encountered when linkifying text.');
    }

    const startIdx = remainingStr.indexOf(match);
    const endIdx = startIdx + match.length;
    const firstHalf = remainingStr.slice(0, startIdx);
    const secondHalf = remainingStr.slice(endIdx);
    if (!_.isEmpty(firstHalf)) {
      elems.push(firstHalf);
    }
    elems.push(getLinkFromMatch(match, i));
    if (!_.isEmpty(secondHalf)) {
      elems.push(secondHalf);
    }
  });
  return elems;
}

export const TargetBlank: React.FC<any> = makeComp(
  ({children, ...passthroughProps}) => {
    return (
      <a target="_blank" rel="noopener noreferrer" {...passthroughProps}>
        {children}
      </a>
    );
  },
  {id: 'TargetBlank'}
);
