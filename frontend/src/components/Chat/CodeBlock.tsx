import React, { Suspense } from 'react';
// Direct style-file imports: the barrel `styles/prism` would pull in every theme.
import oneDark from 'react-syntax-highlighter/dist/esm/styles/prism/one-dark';
import oneLight from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';
import { useThemeStore } from '../../stores/themeStore';

/**
 * react-syntax-highlighter 的完整 Prism 构建带全部语言定义（~1.6MB）。
 * 这里用 light 构建 + 按需注册常用语言，只有消息真正出现代码块时才加载，
 * 常见别名（ts/js/sh/yml…）统一映射到已注册的语言 id。
 */
const PrismHighlighter = React.lazy(async () => {
  const [
    { default: Syntax },
    typescript,
    javascript,
    python,
    bash,
    json,
    sql,
    yaml,
    markdown,
  ] = await Promise.all([
    import('react-syntax-highlighter/dist/esm/light'),
    import('react-syntax-highlighter/dist/esm/languages/prism/typescript'),
    import('react-syntax-highlighter/dist/esm/languages/prism/javascript'),
    import('react-syntax-highlighter/dist/esm/languages/prism/python'),
    import('react-syntax-highlighter/dist/esm/languages/prism/bash'),
    import('react-syntax-highlighter/dist/esm/languages/prism/json'),
    import('react-syntax-highlighter/dist/esm/languages/prism/sql'),
    import('react-syntax-highlighter/dist/esm/languages/prism/yaml'),
    import('react-syntax-highlighter/dist/esm/languages/prism/markdown'),
  ]);

  Syntax.registerLanguage('typescript', typescript.default);
  Syntax.registerLanguage('javascript', javascript.default);
  Syntax.registerLanguage('python', python.default);
  Syntax.registerLanguage('bash', bash.default);
  Syntax.registerLanguage('json', json.default);
  Syntax.registerLanguage('sql', sql.default);
  Syntax.registerLanguage('yaml', yaml.default);
  Syntax.registerLanguage('markdown', markdown.default);

  return { default: Syntax as React.ComponentType<any> };
});

const LANGUAGE_ALIASES: Record<string, string> = {
  ts: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  tsx: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  yml: 'yaml',
  md: 'markdown',
};

interface CodeBlockProps {
  language: string;
  code: string;
}

/** Lazily-loaded, on-demand-language code block used by MessageBubble. */
const CodeBlock: React.FC<CodeBlockProps> = ({ language, code }) => {
  const { resolvedTheme } = useThemeStore();
  const lang = LANGUAGE_ALIASES[language] ?? language;

  return (
    <Suspense
      fallback={
        <pre className="my-3 p-3 rounded-lg bg-gray-900 text-gray-100 text-xs overflow-x-auto">
          {code}
        </pre>
      }
    >
      <PrismHighlighter
        style={resolvedTheme === 'dark' ? oneDark : oneLight}
        language={lang}
        PreTag="div"
        customStyle={{ margin: '0.75rem 0', borderRadius: '0.5rem' }}
      >
        {code}
      </PrismHighlighter>
    </Suspense>
  );
};

export default CodeBlock;
