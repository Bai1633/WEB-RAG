import apiClient from './client';

export interface UserStats {
  knowledge_bases: number;
  documents: {
    total: number;
    completed: number;
    in_flight: number;
    failed: number;
  };
  chunks: number;
  chat_rounds: number;
  total_tokens: number;
}

export const statsApi = {
  async get(): Promise<UserStats> {
    const { data } = await apiClient.get('/api/stats');
    return data?.data;
  },
};
