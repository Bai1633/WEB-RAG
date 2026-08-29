import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Bot,
  Check,
  ChevronDown,
  Copy,
  FileText,
  ShieldQuestion,
  Timer,
  User,
} from 'lucide-react';
import CodeBlock from './CodeBlock';
import { ChatMessage, ChatSource } from '../../types';
import { clsx } from 'clsx';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
  isStreaming?: boolean;
  timestamp?: string;
  metadata?: ChatMessage['metadata'];
}

/** Score badge colour by relevance bucket. */
const scoreTone = (score: number): string => {
  if (score >= 0.7) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300';
  if (score >= 0.4) return 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300';
  return 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400';
};

const SourceCard: React.FC<{ source: ChatSource; index: number }> = ({ source, index }) => {
  const [expanded, setExpanded] = useState(false);
  const preview = source.text_preview?.trim();

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden bg-gray-50/60 dark:bg-gray-900/40">
      <button
        onClick={() => preview && setExpanded((v) => !v)}
        className={clsx(
          'w-full flex items-center gap-2 px-2.5 py-1.5 text-left',
          preview && 'hover:bg-gray-100 dark:hover:bg-gray-700/60 cursor-pointer'
        )}
        title={source.source}
      >
        <FileText size={13} className="flex-shrink-0 text-gray-400" />
        <span className="text-xs text-gray-600 dark:text-gray-300 truncate flex-1">
          <span className="text-gray-400 mr-1">[{index + 1}]</span>
          {source.source || 'Unknown'}
        </span>
        <span
          className={clsx(
            'text-[10px] font-medium px-1.5 py-0.5 rounded flex-shrink-0',
            scoreTone(source.score)
          )}
        >
          {(source.score * 100).toFixed(0)}%
        </span>
        {preview && (
          <ChevronDown
            size={13}
            className={clsx(
              'flex-shrink-0 text-gray-400 transition-transform duration-200',
              expanded && 'rotate-180'
            )}
          />
        )}
      </button>
      {expanded && preview && (
        <p className="px-3 pb-2.5 pt-0.5 text-xs leading-relaxed text-gray-500 dark:text-gray-400 border-t border-gray-200/70 dark:border-gray-700/70 whitespace-pre-wrap animate-fade-in">
          {preview}
        </p>
      )}
    </div>
  );
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  role,
  content,
  sources,
  isStreaming,
  timestamp,
  metadata,
}) => {
  const [copied, setCopied] = useState(false);
  const isUser = role === 'user';

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const hasMeta =
    !isUser &&
    !isStreaming &&
    Boolean(metadata && ((metadata.latency_ms ?? 0) > 0 || (metadata.tokens_used ?? 0) > 0));

  return (
    <div
      className={clsx(
        'flex gap-3 p-4 rounded-xl animate-fade-in-up',
        isUser
          ? 'bg-gradient-to-br from-blue-50 to-indigo-50/70 dark:from-blue-900/15 dark:to-indigo-900/10 ml-auto max-w-3xl flex-row-reverse border border-blue-100/60 dark:border-blue-800/30'
          : 'bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 shadow-soft max-w-4xl'
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser
            ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white'
            : 'bg-gradient-to-br from-gray-100 to-gray-200 dark:from-gray-700 dark:to-gray-600 text-gray-600 dark:text-gray-200'
        )}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
            {isUser ? '你' : 'AI 助手'}
            {timestamp && (
              <span className="ml-2 text-gray-400 dark:text-gray-500">
                {new Date(timestamp).toLocaleTimeString()}
              </span>
            )}
          </span>
          <div className="flex items-center gap-1">
            {hasMeta && (
              <span className="hidden sm:flex items-center gap-2 text-[11px] text-gray-400 dark:text-gray-500 mr-1">
                {metadata?.latency_ms ? (
                  <span className="flex items-center gap-0.5">
                    <Timer size={11} />
                    {(metadata.latency_ms / 1000).toFixed(1)}s
                  </span>
                ) : null}
                {metadata?.tokens_used ? <span>{metadata.tokens_used} tokens</span> : null}
                {metadata?.refused ? (
                  <span className="flex items-center gap-0.5 text-amber-500">
                    <ShieldQuestion size={11} />
                    已拒答
                  </span>
                ) : null}
              </span>
            )}
            {!isUser && content && (
              <button
                onClick={handleCopy}
                className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                title="Copy"
              >
                {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
              </button>
            )}
          </div>
        </div>

        <div className="prose prose-sm dark:prose-invert max-w-none">
          {isUser ? (
            <p className="text-gray-900 dark:text-gray-100 whitespace-pre-wrap">
              {content}
            </p>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ node: _node, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || '');
                  if (!match) {
                    return (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  }
                  return (
                    <CodeBlock
                      language={match[1]}
                      code={String(children).replace(/\n$/, '')}
                    />
                  );
                },
                table({ children }) {
                  return (
                    <div className="overflow-x-auto my-3">
                      <table className="min-w-full border border-gray-200 dark:border-gray-600 rounded-lg">
                        {children}
                      </table>
                    </div>
                  );
                },
                th({ children }) {
                  return (
                    <th className="px-3 py-2 bg-gray-50 dark:bg-gray-700 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      {children}
                    </th>
                  );
                },
                td({ children }) {
                  return (
                    <td className="px-3 py-2 text-sm text-gray-700 dark:text-gray-300 border-t border-gray-200 dark:border-gray-600">
                      {children}
                    </td>
                  );
                },
              }}
            >
              {content}
            </ReactMarkdown>
          )}
          {/* Streaming caret: rendered outside the markdown tree (which only
              accepts plain string children) and shown until the stream ends. */}
          {!isUser && isStreaming && (
            <span
              className="inline-block w-2 h-4 bg-blue-500 animate-blink-caret align-text-bottom"
              aria-hidden
            />
          )}
        </div>

        {/* Sources */}
        {!isUser && sources && sources.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
            <p className="text-[11px] font-medium text-gray-400 dark:text-gray-500 mb-2">
              引用来源 · {sources.length}
            </p>
            <div className="grid gap-1.5">
              {sources.map((source, idx) => (
                <SourceCard key={source.chunk_id || idx} source={source} index={idx} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
