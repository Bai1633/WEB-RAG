import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import StatsPage from '../pages/StatsPage';

vi.mock('../api/stats', () => ({
  statsApi: {
    get: vi.fn(async () => ({
      knowledge_bases: 3,
      documents: { total: 12, completed: 10, in_flight: 1, failed: 1 },
      chunks: 340,
      chat_rounds: 42,
      total_tokens: 15230,
    })),
  },
}));

// 引用必须稳定（mock 前缀变量可安全跨 vi.mock 提升边界）：
// 若每次渲染返回新的 fetchKnowledgeBases，StatsPage 的 useCallback/useEffect
// 依赖会不断变化，导致无限重新加载。
const mockFetchKnowledgeBases = vi.fn(async () => []);

vi.mock('../stores/kbStore', () => ({
  useKBStore: () => ({
    knowledgeBases: [],
    fetchKnowledgeBases: mockFetchKnowledgeBases,
  }),
}));

describe('StatsPage', () => {
  it('renders stat cards from the stats API', async () => {
    render(
      <MemoryRouter>
        <StatsPage />
      </MemoryRouter>
    );

    // 指标卡标签与数值
    expect(await screen.findByText('知识库')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument(); // 文档总数
    expect(screen.getByText('340')).toBeInTheDocument(); // 向量分块
    expect(screen.getByText('42')).toBeInTheDocument(); // 问答轮次

    // 文档状态分布
    expect(screen.getByText('文档处理状态')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('失败（可重试）')).toBeInTheDocument();
  });

  it('renders empty hint when there are no documents', async () => {
    const { statsApi } = await import('../api/stats');
    vi.mocked(statsApi.get).mockResolvedValueOnce({
      knowledge_bases: 0,
      documents: { total: 0, completed: 0, in_flight: 0, failed: 0 },
      chunks: 0,
      chat_rounds: 0,
      total_tokens: 0,
    });

    render(
      <MemoryRouter>
        <StatsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('暂无文档，去知识库管理页上传第一个文档吧')).toBeInTheDocument();
  });
});
