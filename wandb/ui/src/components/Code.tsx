import * as S from './Code.styles';

import Prism from 'prismjs';
import React, {useState, useEffect, useCallback, useRef} from 'react';
import {Icon} from 'semantic-ui-react';
import '../css/Code.less';
import makeComp from '../util/profiler';
import classNames from 'classnames';

// import * as copyText from 'copy-to-clipboard';
// This doesn't work as an import currently, haven't investigated
const copyText = require('copy-to-clipboard');

// Extra prism import
require('prismjs/components/prism-diff');
require('prismjs/components/prism-python');
require('prismjs/components/prism-json');
require('prismjs/components/prism-yaml');

export const CodeBlock: React.FC = makeComp(
  ({children}) => {
    return <S.CodeBlock>{children}</S.CodeBlock>;
  },
  {id: 'CodeBlock'}
);

interface BashProps {
  children?: any;
}

export const Bash: React.FC<BashProps> = makeComp(
  ({children}) => {
    return <div className="code__block bash__terminal">{children}</div>;
  },
  {id: 'Code.Bash', memo: true}
);

interface CommandProps {
  children?: string | string[];
}

export const Command: React.FC<CommandProps> = makeComp(
  ({children}) => {
    return (
      <CopyableCode>
        <div className="bash__command code__item language-bash">
          <div className="bash__command-text language-bash">{children}</div>
        </div>
      </CopyableCode>
    );
  },
  {id: 'Code.Command', memo: true}
);

export const CopyableCode: React.FC = makeComp(
  ({children}) => {
    const [copied, setCopied] = useState(false);
    const codeRef = useRef<HTMLDivElement | null>(null);

    const copy = useCallback(() => {
      const commandText = codeRef.current ? codeRef.current.innerText : '';

      setCopied(true);
      setTimeout(() => setCopied(false), 270);
      return copyText(commandText);
    }, []);

    const iconClass = copied ? 'copied' : '';

    return (
      <div className="copyable__item" onClick={copy}>
        <div ref={codeRef} className="copyable__text language-bash">
          {children}
        </div>
        <Icon name="copy" className={'copyable__copy-icon ' + iconClass} />
      </div>
    );
  },
  {id: 'CopyableCode', memo: true}
);

export const Result: React.FC = makeComp(
  ({children}) => {
    return <div className="code__item bash__result">{children}</div>;
  },
  {id: 'Code.Result', memo: true}
);

export const Python: React.FC = makeComp(
  ({children}) => {
    return (
      <div className="code__block">
        <div className="python__code">{children}</div>
      </div>
    );
  },
  {id: 'Code.Python', memo: true}
);

export const Yaml: React.FC = makeComp(
  ({children}) => {
    return (
      <div className="code__block">
        <div className="yaml__code">{children}</div>
      </div>
    );
  },
  {id: 'Code.Yaml', memo: true}
);

export const Highlight: React.FC = makeComp(
  ({children}) => {
    const codeRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
      if (codeRef.current != null) {
        Prism.highlightElement(codeRef.current);
      }
    }, []);

    return (
      <CopyableCode>
        <div className="code__item">
          <div ref={codeRef} className="language-python">
            {children}
          </div>
        </div>
      </CopyableCode>
    );
  },
  {id: 'Code.Highlight', memo: true}
);

export const Static: React.FC<{className?: string}> = makeComp(
  ({className, children}) => {
    const codeRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
      if (codeRef.current != null) {
        Prism.highlightElement(codeRef.current);
      }
    }, []);

    return (
      <div className={classNames('code__item', className)}>
        <div ref={codeRef} className="language-python">
          {children}
        </div>
      </div>
    );
  },
  {id: 'Code.Static', memo: true}
);

type Size = 'small' | 'medium';

interface TearProps {
  size?: Size;
  text?: string;
}

export const Tear: React.FC<TearProps> = makeComp(
  opts => (
    <div className={`code__tear code__tear--${opts.size}`}>{opts.text}</div>
  ),
  {id: 'Code.Tear', memo: true}
);
