import { create } from 'zustand';
import { KnowledgeBase, Document, KBMember } from '../types';
import { knowledgeBaseApi } from '../api/knowledgeBase';
import { documentApi } from '../api/document';

interface KBState {
  knowledgeBases: KnowledgeBase[];
  currentKB: KnowledgeBase | null;
  documents: Document[];
  members: KBMember[];
  isLoading: boolean;
  error: string | null;

  fetchKnowledgeBases: () => Promise<void>;
  fetchKB: (id: string) => Promise<void>;
  createKB: (name: string, description?: string) => Promise<KnowledgeBase>;
  updateKB: (id: string, data: { name?: string; description?: string }) => Promise<void>;
  deleteKB: (id: string) => Promise<void>;
  setCurrentKB: (kb: KnowledgeBase | null) => void;

  fetchDocuments: (kbId: string, status?: string) => Promise<void>;
  uploadDocument: (kbId: string, file: File) => Promise<void>;
  deleteDocument: (kbId: string, docId: string) => Promise<void>;
  retryDocument: (kbId: string, docId: string) => Promise<void>;
  pollDocumentStatus: (kbId: string, docId: string) => Promise<void>;

  fetchMembers: (kbId: string) => Promise<void>;
  addMember: (kbId: string, userEmail: string, role: string) => Promise<void>;
  updateMemberRole: (kbId: string, userId: string, role: string) => Promise<void>;
  removeMember: (kbId: string, userId: string) => Promise<void>;

  clearError: () => void;
}

export const useKBStore = create<KBState>((set, get) => ({
  knowledgeBases: [],
  currentKB: null,
  documents: [],
  members: [],
  isLoading: false,
  error: null,

  fetchKnowledgeBases: async () => {
    set({ isLoading: true, error: null });
    try {
      const kbs = await knowledgeBaseApi.list();
      set({ knowledgeBases: kbs, isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to fetch knowledge bases', isLoading: false });
    }
  },

  fetchKB: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const kb = await knowledgeBaseApi.get(id);
      set({ currentKB: kb, isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to fetch knowledge base', isLoading: false });
    }
  },

  createKB: async (name: string, description?: string) => {
    set({ isLoading: true, error: null });
    try {
      const kb = await knowledgeBaseApi.create({ name, description });
      set((state) => ({
        knowledgeBases: [kb, ...state.knowledgeBases],
        isLoading: false,
      }));
      return kb;
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to create knowledge base', isLoading: false });
      throw error;
    }
  },

  updateKB: async (id: string, data: { name?: string; description?: string }) => {
    set({ isLoading: true, error: null });
    try {
      const kb = await knowledgeBaseApi.update(id, data);
      set((state) => ({
        knowledgeBases: state.knowledgeBases.map((k) => (k.id === id ? kb : k)),
        currentKB: state.currentKB?.id === id ? kb : state.currentKB,
        isLoading: false,
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to update knowledge base', isLoading: false });
      throw error;
    }
  },

  deleteKB: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      await knowledgeBaseApi.delete(id);
      set((state) => ({
        knowledgeBases: state.knowledgeBases.filter((k) => k.id !== id),
        currentKB: state.currentKB?.id === id ? null : state.currentKB,
        isLoading: false,
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to delete knowledge base', isLoading: false });
      throw error;
    }
  },

  setCurrentKB: (kb: KnowledgeBase | null) => set({ currentKB: kb }),

  fetchDocuments: async (kbId: string, status?: string) => {
    set({ isLoading: true, error: null });
    try {
      const docs = await documentApi.list(kbId, status);
      set({ documents: docs, isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to fetch documents', isLoading: false });
    }
  },

  uploadDocument: async (kbId: string, file: File) => {
    set({ isLoading: true, error: null });
    try {
      await documentApi.upload(kbId, file);
      set({ isLoading: false });
      await get().fetchDocuments(kbId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to upload document', isLoading: false });
      throw error;
    }
  },

  deleteDocument: async (kbId: string, docId: string) => {
    try {
      await documentApi.delete(kbId, docId);
      set((state) => ({
        documents: state.documents.filter((d) => d.id !== docId),
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to delete document' });
      throw error;
    }
  },

  retryDocument: async (kbId: string, docId: string) => {
    try {
      await documentApi.retry(kbId, docId);
      await get().fetchDocuments(kbId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to retry document' });
      throw error;
    }
  },

  pollDocumentStatus: async (kbId: string, docId: string) => {
    try {
      const status = await documentApi.getStatus(kbId, docId);
      set((state) => ({
        documents: state.documents.map((d) =>
          d.id === docId
            ? {
                ...d,
                status: status.status,
                progress: status.progress,
                error: status.error,
                chunk_count: status.chunk_count,
              }
            : d
        ),
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to get document status' });
    }
  },

  fetchMembers: async (kbId: string) => {
    set({ isLoading: true, error: null });
    try {
      const members = await knowledgeBaseApi.listMembers(kbId);
      set({ members, isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to fetch members', isLoading: false });
    }
  },

  addMember: async (kbId: string, userEmail: string, role: string) => {
    set({ isLoading: true, error: null });
    try {
      await knowledgeBaseApi.addMember(kbId, userEmail, role);
      await get().fetchMembers(kbId);
      set({ isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to add member', isLoading: false });
      throw error;
    }
  },

  updateMemberRole: async (kbId: string, userId: string, role: string) => {
    set({ isLoading: true, error: null });
    try {
      await knowledgeBaseApi.updateMemberRole(kbId, userId, role);
      await get().fetchMembers(kbId);
      set({ isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to update member role', isLoading: false });
      throw error;
    }
  },

  removeMember: async (kbId: string, userId: string) => {
    set({ isLoading: true, error: null });
    try {
      await knowledgeBaseApi.removeMember(kbId, userId);
      await get().fetchMembers(kbId);
      set({ isLoading: false });
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'Failed to remove member', isLoading: false });
      throw error;
    }
  },

  clearError: () => set({ error: null }),
}));
