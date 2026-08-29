import React, { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Send, StopCircle, Settings, MessageSquarePlus } from 'lucide-react';
import { MessageBubble } from '../components/Chat/MessageBubble';
import { TypingIndicator } from '../components/Chat/TypingIndicator';
import { useKBStore } from '../stores/kbStore';
import { chatApi, ChatConversationSummary } from '../api/chat';
import { ChatMessage, ChatSource } from '../types';
import { clsx } from 'clsx';

const DEFAULT_SUGGESTIONS = [
  '这份知识库主要涵盖哪些内容？',
  '帮我总结一下文档的核心要点',
  '有哪些关键的步骤或流程？',
  '文档中提到了哪些数据或指标？',
];

const ChatPage: React.FC = () => {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { currentKB, fetchKB } = useKBStore();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const abortRef = useRef<(() => void) | null>(null);
  // Session-level conversation ID for multi-turn isolation
  const conversationId = useRef<string>(crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const loadHistory = async (id: string) => {
    try {
      const history = await chatApi.getHistory(id, 0, 50, conversationId.current);
      // 后端按 created_at DESC 返回（最新在前）。先在"记录级"按时间升序稳定排序（旧→新），
      // 再逐条展开为 [user, assistant] 配对。这样每条对话内部顺序正确，整体也按时间升序，
      // 且保留后端 DESC + limit 取"最近 N 条"的分页语义（历史超 50 条也不会丢最新）。
      // 注意：不能在展开后的扁平数组上 reverse —— 那会把每条对话内的 [user, assistant] 也颠倒。
      const sorted = [...(history ?? [])].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      const historyMessages: ChatMessage[] = sorted.flatMap((item: any) => [
        {
          id: `hist-user-${item.id}`,
          role: 'user' as const,
          content: item.question,
          timestamp: item.created_at,
        },
        {
          id: `hist-assistant-${item.id}`,
          role: 'assistant' as const,
          content: item.answer,
          sources: Array.isArray(item.sources) ? item.sources : [],
          timestamp: item.created_at,
          metadata: {
            latency_ms: item.latency_ms,
            tokens_used: item.tokens,
          },
        },
      ]);
      setMessages(historyMessages);
    } catch (err) {
      // 历史加载失败不应阻断聊天主流程，保持空对话即可
      console.error('Failed to load chat history', err);
    }
  };

  const loadConversations = async (id: string): Promise<ChatConversationSummary[]> => {
    try {
      const list = await chatApi.getConversations(id);
      setConversations(list ?? []);
      return list ?? [];
    } catch (err) {
      // 会话列表加载失败不阻断主流程
      console.error('Failed to load conversations', err);
      return [];
    }
  };

  /** 推荐问题优先取该知识库里用户最近问过的问题，没有历史时回退到通用默认。 */
  const loadSuggestions = async (id: string) => {
    try {
      const records = await chatApi.getHistory(id, 0, 20);
      const questions: string[] = [];
      for (const r of records ?? []) {
        const q = String(r?.question || '').trim();
        if (q && q.length <= 40 && !questions.includes(q)) questions.push(q);
        if (questions.length >= 4) break;
      }
      if (questions.length > 0) {
        setSuggestions([...questions, ...DEFAULT_SUGGESTIONS].slice(0, 4));
      }
    } catch {
      // 保持默认推荐
    }
  };

  useEffect(() => {
    if (!kbId) return;
    fetchKB(kbId);
    (async () => {
      // 有历史会话则自动恢复最近的一个（后端按 last_active 降序），
      // 否则以全新 conversationId 进入空对话。
      const list = await loadConversations(kbId);
      if (list.length > 0) {
        conversationId.current = list[0].conversation_id;
      }
      loadHistory(kbId);
      loadSuggestions(kbId);
    })();
  }, [kbId, fetchKB]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = async (presetText?: string) => {
    const text = (presetText ?? input).trim();
    if (!text || isSending || !kbId) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    const assistantMessage: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      sources: [],
      isStreaming: true,
      timestamp: new Date().toISOString(),
      metadata: {
        latency_ms: 0,
        tokens_used: 0,
        confidence: 0,
      },
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput('');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
    setIsSending(true);

    // Build history from recent messages for multi-turn context
    const recentHistory = messages
      .filter((m) => !m.isStreaming)
      .slice(-10)  // last 10 messages (5 rounds)
      .map((m) => ({ role: m.role, content: m.content }));

    // Capture the cleanup function returned by streamChat
    const cancel = chatApi.streamChat(
      kbId,
      userMessage.content,
      {
        onSources: (sources: ChatSource[]) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id ? { ...m, sources } : m
            )
          );
        },
      onContent: (chunk: string) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? { ...m, content: m.content + chunk }
              : m
          )
        );
      },
      onDone: (metadata: any) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? {
                  ...m,
                  isStreaming: false,
                  metadata: {
                    ...m.metadata,
                    ...metadata,
                  },
                }
              : m
          )
        );
        setIsSending(false);
        abortRef.current = null;
        // 新会话在首条消息落库后出现在会话列表中
        if (kbId) void loadConversations(kbId);
      },
      onError: (error: string) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? {
                  ...m,
                  content: `Error: ${error}`,
                  isStreaming: false,
                }
              : m
          )
        );
        setIsSending(false);
        abortRef.current = null;
      },
    },
    { history: recentHistory, conversation_id: conversationId.current }
  );
    abortRef.current = cancel;
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
      setIsSending(false);
      setMessages((prev) =>
        prev.map((m) =>
          m.isStreaming ? { ...m, isStreaming: false } : m
        )
      );
    }
  };

  const handleNewChat = () => {
    conversationId.current = crypto.randomUUID();
    setMessages([]);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /** Auto-grow the textarea up to max-h-40 as the user types. */
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <div className="flex items-center justify-between px-4 py-3 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <h1 className="font-semibold text-gray-900 dark:text-white">
            {currentKB?.name || 'Chat'}
          </h1>
          {currentKB && (
            <span className="text-xs text-gray-500 dark:text-gray-400 hidden sm:inline">
              {currentKB.embed_model} • {currentKB.embed_dim}d
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {conversations.length > 0 && (
            <select
              value={
                conversations.some((c) => c.conversation_id === conversationId.current)
                  ? conversationId.current
                  : ''
              }
              onChange={(e) => {
                const id = e.target.value;
                if (!id || !kbId) return;
                conversationId.current = id;
                loadHistory(kbId);
              }}
              className="max-w-[180px] sm:max-w-[260px] text-xs text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 truncate"
              title="Switch conversation"
            >
              <option value="">新对话</option>
              {conversations.map((c) => (
                <option key={c.conversation_id} value={c.conversation_id}>
                  {new Date(c.last_active).toLocaleString()} · {c.rounds} 轮
                </option>
              ))}
            </select>
          )}
          <button
            onClick={handleNewChat}
            className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            title="New chat"
          >
            <MessageSquarePlus size={18} />
          </button>
          <button
            onClick={() => navigate(`/manage`)}
            className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            title="Manage documents"
          >
            <Settings size={18} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
        <div className="max-w-4xl mx-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full py-16 animate-fade-in-up">
              <span className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/10 text-blue-500 dark:text-blue-400 mb-5">
                <MessageSquarePlus size={32} />
              </span>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                向知识库提问
              </h2>
              <p className="text-gray-500 dark:text-gray-400 text-center max-w-md mb-8">
                我会检索「{currentKB?.name || '知识库'}」中的文档，
                给出带引用来源的回答。
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
                {suggestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => handleSend(q)}
                    disabled={!currentKB || isSending}
                    className="text-left text-sm px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:border-blue-300 dark:hover:border-blue-600 hover:text-blue-600 dark:hover:text-blue-400 hover:shadow-soft transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <MessageBubble
                key={message.id}
                role={message.role}
                content={message.content}
                sources={message.sources}
                isStreaming={message.isStreaming}
                timestamp={message.timestamp}
                metadata={message.metadata}
              />
            ))
          )}
          {isSending && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
            <TypingIndicator />
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
        <div className="max-w-4xl mx-auto">
          <div className="relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
              rows={1}
              disabled={!currentKB}
              className={clsx(
                'w-full px-4 py-3 pr-14 border border-gray-300 dark:border-gray-600 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/60 dark:bg-gray-700 dark:text-white transition-shadow',
                'max-h-40 overflow-y-auto'
              )}
              style={{ minHeight: '48px' }}
            />
            <div className="absolute right-2 bottom-2 flex items-center gap-1">
              {isSending ? (
                <button
                  onClick={handleStop}
                  className="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                  title="停止生成"
                >
                  <StopCircle size={20} />
                </button>
              ) : (
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim() || !currentKB}
                  className="p-2 text-white bg-gradient-to-r from-blue-600 to-indigo-600 rounded-lg hover:from-blue-700 hover:to-indigo-700 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                  title="发送"
                >
                  <Send size={20} />
                </button>
              )}
            </div>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-2 text-center">
            回答内容由 AI 生成，请以知识库引用来源为准
          </p>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
