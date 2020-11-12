import {produce} from 'immer';
import * as _ from 'lodash';
import parse from 'remark-parse';
import unified, {Plugin} from 'unified';

const sanitize = require('rehype-sanitize');
const stringify = require('rehype-stringify');
const math = require('remark-math');
const remark2rehype = require('remark-rehype');
const emoji = require('remark-emoji');
const katex = require('rehype-katex');
const gh = require('hast-util-sanitize/lib/github');
const toString = require('mdast-util-to-string');
const parseHTML = require('rehype-parse');

const visit = require('unist-util-visit');

const sanitizeRules = _.merge(gh, {
  attributes: {'*': ['className', 'style']},
});

export function generateHTML(markdown: string) {
  // IMPORTANT: We must sanitize as the final step of the pipeline to prevent XSS
  const vfile = unified()
    .use(parse)
    .use(math)
    .use(emoji)
    .use(centerText)
    .use(remark2rehype)
    .use(katex)
    .use(stringify)
    .use(sanitize, sanitizeRules)
    .processSync(markdown);
  if (typeof vfile.contents === 'string') {
    vfile.contents = blankifyLinks(vfile.contents);
  }
  return vfile;
}

export function sanitizeHTML(html: string) {
  return unified()
    .use(parseHTML)
    .use(stringify)
    .use(sanitize, sanitizeRules)
    .processSync(html)
    .toString();
}

function blankifyLinks(html: string): string {
  return html.replace(/<a href="[^"]+"/g, match => `${match} target="_blank"`);
}

// NOTE: The library does not provide the types, this is a partial type
// that types the interface we access here. To use more of the underlying data
// extend this type
interface ASTNode {
  children: ASTNode[];
  type: string;
  value?: string;
  data: {
    hName: string;
    hProperties: {className: string};
  };
  // unknown: unknown
}

// Converts -> Text <- To a centered node in the markdown syntax
// Works at the paragraph level allowing link embedding
const centerText: Plugin = settings => markdownAST => {
  visit(markdownAST, 'paragraph', (node: ASTNode) => {
    const text = toString(node).trim();
    const isCenter =
      text.slice(0, 3) === '-> ' &&
      text.slice(text.length - 3, text.length) === ' <-';

    if (!isCenter) {
      return;
    }
    const originalNode = _.clone(node);
    const last = node.children.length - 1;
    const newChildren = produce(node.children, draft => {
      // Don't use leading ^ for first regex because
      // the AST parsing captures the leading linebreak
      draft[0].value = draft[0]?.value?.trim().replace(/->\s*/, '');
      draft[last].value = draft[last]?.value?.trim().replace(/\s*<-$/, '');
    });
    originalNode.children = newChildren;
    node.type = 'center';
    node.data = {
      hName: 'span',
      hProperties: {className: 'center'},
    };
    node.children = [originalNode];
  });
  return markdownAST;
};
