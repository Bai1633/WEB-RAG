import apiClient from './client';
import { ChatSource } from '../types';

export interface ChatResult {
  answer: string;
  sources: ChatSource[];
  confidence: number;
  tokens_used: number;
  latency_ms: number;
  refused: boolean;
  refusal_reason: string;
}

export interface ChatConversationSummary {
  conversation_id: string;
  last_active: string;
  rounds: number;
}

export interface ChatStreamCallbacks {
  onSources?: (sources: ChatSource[]) => void;
  onContent?: (chunk: string) => void;
  onDone?: (metadata: { latency_ms: number; tokens_used: number; confidence: number }) => void;
  onError?: (error: string) => void;
}

export interface ChatStreamOptions {
  history?: { role: string; content: string }[];
  conversation_id?: string;
}

export const chatApi = {
  async chat(kbId: string, question: string): Promise<ChatResult> {
    const { data } = await apiClient.post(`/api/knowledge-bases/${kbId}/chat`, {
      question,
      stream: false,
    });
    return data;
  },

  streamChat(
    kbId: string,
    question: string,
    callbacks: ChatStreamCallbacks,
    options?: ChatStreamOptions,
  ): () => void {
    const token = localStorage.getItem('access_token');
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

    const controller = new AbortController();
    const signal = controller.signal;

    const body: Record<string, unknown> = { question, stream: true };
    if (options?.history) body.history = options.history;
    if (options?.conversation_id) body.conversation_id = options.conversation_id;

    const run = async () => {
      try {
        const response = await fetch(
          `${baseUrl}/api/knowledge-bases/${kbId}/chat`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(body),
            signal,
          }
        );

        if (!response.ok) {
          const errorText = await response.text();
          callbacks.onError?.(`HTTP ${response.status}: ${errorText}`);
          return;
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        if (!reader) {
          callbacks.onError?.('No response body');
          return;
        }

        let result = await reader.read();
        while (!result.done) {
          const { value } = result;
          buffer += decoder.decode(value, { stream: true });

          // Parse SSE events
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const event = JSON.parse(dataStr);
                switch (event.type) {
                  case 'sources':
                    callbacks.onSources?.(event.data);
                    break;
                  case 'content':
                    callbacks.onContent?.(event.data);
                    break;
                  case 'done':
                    callbacks.onDone?.(event.data);
                    break;
                  case 'error':
                    callbacks.onError?.(event.data);
                    break;
                }
              } catch (e) {
                // Not JSON, might be raw text
              }
            }
          }
          result = await reader.read();
        }
      } catch (error: any) {
        if (error.name !== 'AbortError') {
          callbacks.onError?.(error.message || 'Stream error');
        }
      }
    };

    run();

    return () => {
      controller.abort();
    };
  },

  async getHistory(kbId: string, skip = 0, limit = 50, conversationId?: string): Promise<any[]> {
    const params: Record<string, unknown> = { skip, limit };
    if (conversationId) params.conversation_id = conversationId;
    const { data } = await apiClient.get(`/api/knowledge-bases/${kbId}/chat/history`, {
      params,
    });
    // 后端返回分页结构 { data: [...], pagination: {...} }，解出 items 数组
    return data?.data ?? [];
  },

  async getConversations(kbId: string): Promise<ChatConversationSummary[]> {
    const { data } = await apiClient.get(
      `/api/knowledge-bases/${kbId}/chat/conversations`
    );
    // 后端按 last_active 降序返回
    return data?.data ?? [];
  },
};