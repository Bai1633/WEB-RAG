import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MessageBubble } from '../components/Chat/MessageBubble';

describe('MessageBubble', () => {
  it('renders source cards with score badges and expands preview', async () => {
    render(
      <MessageBubble
        role="assistant"
        content="回答内容"
        sources={[
          {
            chunk_id: 'c1',
            doc_id: 'd1',
            source: 'rag_pipeline.md',
            score: 0.8,
            text_preview: '这是被引用的原文片段',
          },
        ]}
        metadata={{ latency_ms: 1234, tokens_used: 56 }}
      />
    );

    expect(screen.getByText('引用来源 · 1')).toBeInTheDocument();
    expect(screen.getByText('rag_pipeline.md')).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
    // 元信息脚注
    expect(screen.getByText('1.2s')).toBeInTheDocument();
    expect(screen.getByText('56 tokens')).toBeInTheDocument();

    // 默认不展示原文，点击后展开
    expect(screen.queryByText('这是被引用的原文片段')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('rag_pipeline.md'));
    expect(await screen.findByText('这是被引用的原文片段')).toBeInTheDocument();
  });

  it('hides metadata footer while streaming', () => {
    render(<MessageBubble role="assistant" content="" isStreaming metadata={{ latency_ms: 0, tokens_used: 0 }} />);
    expect(screen.queryByText(/tokens/)).not.toBeInTheDocument();
  });

  it('renders user messages without sources', () => {
    render(<MessageBubble role="user" content="用户的问题" />);
    expect(screen.getByText('用户的问题')).toBeInTheDocument();
    expect(screen.getByText('你')).toBeInTheDocument();
    expect(screen.queryByText('引用来源')).not.toBeInTheDocument();
  });
});
