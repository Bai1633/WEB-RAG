// Global type definitions

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface KnowledgeBase {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  embed_model: string;
  embed_dim: number;
  vector_table: string;
  created_at: string;
  updated_at: string;
  doc_count?: number;
  member_count?: number;
  // 当前用户在该知识库中的角色，用于前端做权限感知 UI
  role?: 'owner' | 'editor' | 'viewer';
}

export interface Document {
  id: string;
  kb_id: string;
  filename: string;
  file_path: string;
  file_size: number;
  mime_type: string;
  status: 'uploaded' | 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  error: string;
  chunk_count: number;
  task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatSource {
  chunk_id: string;
  doc_id: string;
  source: string;
  score: number;
  text_preview: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
  timestamp?: string;
  isStreaming?: boolean;
  metadata?: {
    latency_ms?: number;
    tokens_used?: number;
    confidence?: number;
    refused?: boolean;
    refusal_reason?: string;
  };
}

export interface ChatSSEEvent {
  type: 'sources' | 'content' | 'done' | 'error';
  data: any;
}

export type Theme = 'light' | 'dark' | 'system';

export interface KBMember {
  kb_id: string;
  user_id: string;
  email: string;
  role: 'owner' | 'editor' | 'viewer';
  created_at: string;
}
