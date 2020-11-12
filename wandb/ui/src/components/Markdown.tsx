import '../css/Markdown.less';

import * as Prism from 'prismjs';
import React, {
  useState,
  useEffect,
  useLayoutEffect,
  useCallback,
  useRef,
} from 'react';
import vfile from 'vfile';
import {Item} from 'semantic-ui-react';
import {generateHTML} from '../util/markdown';

import 'katex/dist/katex.css';
import makeComp from '../util/profiler';
require('prismjs/components/prism-markdown');

const formatContent = async (content: string, condensed?: boolean) => {
  if (!content || content.length === 0) {
    return '';
  }
  if (condensed) {
    const parts = content.split(/#+/);
    content = parts[0].length === 0 ? '### ' + parts[1] : parts[0];
    return await generateHTML(content);
  } else {
    return await generateHTML(content);
  }
};

interface MarkdownEditorProps {
  content: string;
  condensed?: boolean;
  onContentHeightChange?(h: number): void;
}

const Markdown: React.FC<MarkdownEditorProps> = makeComp(
  ({content, condensed, onContentHeightChange}) => {
    const ref = useRef<HTMLDivElement>(null);
    const [html, setHTML] = useState<string | vfile.VFile>(
      '<div class="ui active loader"/>'
    );

    useEffect(() => {
      let cancelled = false;
      formatContent(content, condensed).then(formatted => {
        if (cancelled) {
          return;
        }
        setHTML(formatted);
      });

      return () => {
        cancelled = true;
      };
    }, [content, condensed]);

    useLayoutEffect(() => {
      if (ref.current) {
        const code = ref.current.querySelectorAll('code');
        // tslint:disable-next-line:prefer-for-of
        for (let i = 0; i < code.length; i++) {
          Prism.highlightElement(code[i]);
        }
      }
    }, [html]);

    const lastHeight = useRef<number | null>(null);

    const updateHeight = useCallback(() => {
      const contentHeight = ref.current?.offsetHeight;
      if (contentHeight != null && contentHeight !== lastHeight.current) {
        lastHeight.current = contentHeight;
        onContentHeightChange?.(contentHeight);
      }
    }, [onContentHeightChange]);

    useEffect(() => {
      if (ref.current == null || onContentHeightChange == null) {
        return;
      }
      window.addEventListener('resize', updateHeight);
      // Images load asynchronously and affect the content height
      ref.current.querySelectorAll('img').forEach(img => {
        img.addEventListener('load', updateHeight);
      });
      updateHeight();
      return () => {
        window.removeEventListener('resize', updateHeight);
      };
    });

    return (
      <div ref={ref} className="markdown-content">
        <Item.Description
          className={condensed ? '' : 'markdown'}
          dangerouslySetInnerHTML={{
            __html: html,
          }}
        />
      </div>
    );
  },
  {id: 'Markdown'}
);
export default Markdown;
