import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Sidebar } from '../components/Layout/Sidebar';

// vi.mock is hoisted, so the store is stubbed once with an empty KB list;
// the with-data case is covered via StatsPage's own data-driven test.
vi.mock('../../stores/kbStore', () => ({
  useKBStore: () => ({
    knowledgeBases: [],
    fetchKnowledgeBases: vi.fn(async () => []),
    setCurrentKB: vi.fn(),
  }),
}));

describe('Sidebar', () => {
  it('renders navigation entries and the empty-state hint', async () => {
    render(
      <MemoryRouter initialEntries={['/stats']}>
        <Sidebar isOpen onClose={() => {}} />
      </MemoryRouter>
    );

    expect(screen.getByText('数据看板')).toBeInTheDocument();
    expect(screen.getByText('知识库管理')).toBeInTheDocument();
    expect(await screen.findByText(/还没有知识库/)).toBeInTheDocument();
  });
});
