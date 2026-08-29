import apiClient from './client';
import { KnowledgeBase, KBMember } from '../types';

export const knowledgeBaseApi = {
  async list(): Promise<KnowledgeBase[]> {
    const { data } = await apiClient.get('/api/knowledge-bases');
    // 后端返回分页结构 { data: [...], pagination: {...} }，解出 items 数组
    return data?.data ?? [];
  },

  async get(id: string): Promise<KnowledgeBase> {
    const { data } = await apiClient.get(`/api/knowledge-bases/${id}`);
    return data;
  },

  async create(params: {
    name: string;
    description?: string;
    embed_model?: string;
    embed_dim?: number;
  }): Promise<KnowledgeBase> {
    const { data } = await apiClient.post('/api/knowledge-bases', params);
    return data;
  },

  async update(id: string, params: { name?: string; description?: string }): Promise<KnowledgeBase> {
    const { data } = await apiClient.patch(`/api/knowledge-bases/${id}`, params);
    return data;
  },

  async delete(id: string): Promise<void> {
    await apiClient.delete(`/api/knowledge-bases/${id}`);
  },

  // Members
  async listMembers(kbId: string): Promise<KBMember[]> {
    const { data } = await apiClient.get(`/api/knowledge-bases/${kbId}/members`);
    return data;
  },

  async addMember(kbId: string, userEmail: string, role: string): Promise<KBMember> {
    const { data } = await apiClient.post(`/api/knowledge-bases/${kbId}/members`, {
      user_email: userEmail,
      role,
    });
    return data;
  },

  async updateMemberRole(kbId: string, userId: string, role: string): Promise<KBMember> {
    const { data } = await apiClient.patch(`/api/knowledge-bases/${kbId}/members/${userId}`, {
      role,
    });
    return data;
  },

  async removeMember(kbId: string, userId: string): Promise<void> {
    await apiClient.delete(`/api/knowledge-bases/${kbId}/members/${userId}`);
  },
};
