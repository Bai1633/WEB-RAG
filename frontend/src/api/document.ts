import apiClient from './client';
import { Document } from '../types';

export const documentApi = {
  async list(kbId: string, status?: string): Promise<Document[]> {
    const params = status ? { status } : {};
    const { data } = await apiClient.get(`/api/knowledge-bases/${kbId}/documents`, { params });
    // 后端返回分页结构 { data: [...], pagination: {...} }，解出 items 数组
    return data?.data ?? [];
  },

  async get(kbId: string, docId: string): Promise<Document> {
    const { data } = await apiClient.get(`/api/knowledge-bases/${kbId}/documents/${docId}`);
    return data;
  },

  async upload(
    kbId: string,
    file: File,
    onProgress?: (progress: number) => void
  ): Promise<{ document_id: string; task_id: string; status: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const { data } = await apiClient.post(
      `/api/knowledge-bases/${kbId}/documents/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onProgress(progress);
          }
        },
      }
    );
    return data;
  },

  async delete(kbId: string, docId: string): Promise<void> {
    await apiClient.delete(`/api/knowledge-bases/${kbId}/documents/${docId}`);
  },

  async retry(kbId: string, docId: string): Promise<{ document_id: string; task_id: string; status: string }> {
    const { data } = await apiClient.post(
      `/api/knowledge-bases/${kbId}/documents/${docId}/retry`
    );
    return data;
  },

  async getStatus(kbId: string, docId: string): Promise<any> {
    const { data } = await apiClient.get(
      `/api/knowledge-bases/${kbId}/documents/${docId}/status`
    );
    return data;
  },
};
