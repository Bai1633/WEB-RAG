import React, { useEffect, useState } from 'react';
import {
  Plus,
  Trash2,
  Upload,
  RefreshCw,
  FileText,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  Users,
  UserPlus,
} from 'lucide-react';
import { useKBStore } from '../stores/kbStore';
import { useAuthStore } from '../stores/authStore';
import { KnowledgeBase, KBMember } from '../types';
import { clsx } from 'clsx';

// 角色操作权限：最高权限的人才有权操作
const ROLE_LEVEL: Record<string, number> = { viewer: 1, editor: 2, owner: 3 };

const ManagePage: React.FC = () => {
  const {
    knowledgeBases,
    documents,
    members,
    isLoading,
    error,
    fetchKnowledgeBases,
    createKB,
    deleteKB,
    fetchDocuments,
    uploadDocument,
    deleteDocument,
    retryDocument,
    pollDocumentStatus,
    fetchMembers,
    addMember,
    updateMemberRole,
    removeMember,
    clearError,
  } = useKBStore();
  const currentUser = useAuthStore((s) => s.user);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // Members management modal state
  const [showMembersModal, setShowMembersModal] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberRole, setMemberRole] = useState<'editor' | 'viewer'>('viewer');

  // Current KB permission level (fall back to viewer if unknown)
  const currentRole = selectedKb?.role ?? 'viewer';
  const currentRoleLevel = ROLE_LEVEL[currentRole] ?? 1;
  const canEdit = currentRoleLevel >= ROLE_LEVEL.editor; // 可上传/删除文档
  const canManage = currentRoleLevel >= ROLE_LEVEL.owner; // 可删除 KB / 管理成员

  useEffect(() => {
    fetchKnowledgeBases();
  }, [fetchKnowledgeBases]);

  useEffect(() => {
    if (selectedKb) {
      fetchDocuments(selectedKb.id);
    }
  }, [selectedKb, fetchDocuments]);

  // Load members whenever the members modal opens
  useEffect(() => {
    if (showMembersModal && selectedKb) {
      fetchMembers(selectedKb.id);
    }
  }, [showMembersModal, selectedKb, fetchMembers]);

  useEffect(() => {
    if (!selectedKb) return;

    const processingDocs = documents.filter(
      (d) => d.status === 'uploaded' || d.status === 'queued' || d.status === 'processing'
    );

    if (processingDocs.length === 0) return;

    const interval = setInterval(() => {
      processingDocs.forEach((doc) => {
        pollDocumentStatus(selectedKb.id, doc.id);
      });
    }, 2000);

    return () => clearInterval(interval);
  }, [selectedKb, documents, pollDocumentStatus]);

  const handleCreateKB = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createKB(newKbName, newKbDesc);
      setShowCreateModal(false);
      setNewKbName('');
      setNewKbDesc('');
    } catch {
      // 错误已写入全局 store，由页面顶部横幅展示
    }
  };

  const handleDeleteKB = async (kb: KnowledgeBase) => {
    if (window.confirm(`Are you sure you want to delete "${kb.name}"? This cannot be undone.`)) {
      await deleteKB(kb.id);
      if (selectedKb?.id === kb.id) {
        setSelectedKb(null);
      }
    }
  };

  const uploadFiles = async (files: FileList | File[]) => {
    if (!selectedKb || isUploading) return;
    setIsUploading(true);
    clearError();
    try {
      for (const file of Array.from(files)) {
        await uploadDocument(selectedKb.id, file);
      }
    } catch {
      // 单个文件失败会抛出到 store.error，由文档区横幅展示
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedKb || !e.target.files?.length) return;
    await uploadFiles(e.target.files);
    e.target.value = '';
  };

  const handleDrop = async (e: React.DragEvent) => {
    if (!canEdit || !selectedKb) return;
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) {
      await uploadFiles(e.dataTransfer.files);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!canEdit || !selectedKb) return;
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!canEdit) return;
    // Only leave when the pointer exits the panel itself, not child elements
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  };

  const handleOpenMembers = () => {
    setMemberEmail('');
    setMemberRole('viewer');
    setShowMembersModal(true);
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedKb || !memberEmail.trim()) return;
    try {
      await addMember(selectedKb.id, memberEmail.trim(), memberRole);
      setMemberEmail('');
    } catch {
      // error is shown via store
    }
  };

  const handleChangeRole = async (member: KBMember, role: string) => {
    if (!selectedKb || member.role === role) return;
    if (window.confirm(`Change role of user to "${role}"?`)) {
      try {
        await updateMemberRole(selectedKb.id, member.user_id, role);
      } catch {
        // 错误已写入全局 store
      }
    }
  };

  const handleRemoveMember = async (member: KBMember) => {
    if (!selectedKb) return;
    if (window.confirm('Remove this member from the knowledge base?')) {
      try {
        await removeMember(selectedKb.id, member.user_id);
      } catch {
        // 错误已写入全局 store
      }
    }
  };

  const roleBadge = (role?: string) => {
    const styles: Record<string, string> = {
      owner: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
      editor: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
      viewer: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
    };
    return (
      <span className={clsx('px-1.5 py-0.5 rounded text-xs font-medium', styles[role || 'viewer'] || styles.viewer)}>
        {role || 'viewer'}
      </span>
    );
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="text-green-500" size={16} />;
      case 'failed':
        return <XCircle className="text-red-500" size={16} />;
      case 'processing':
      case 'queued':
      case 'uploaded':
        return <Loader2 className="text-blue-500 animate-spin" size={16} />;
      default:
        return <Clock className="text-gray-400" size={16} />;
    }
  };

  const getStatusText = (status: string) => {
    const map: Record<string, string> = {
      uploaded: 'Uploaded',
      queued: 'Queued',
      processing: 'Processing',
      completed: 'Completed',
      failed: 'Failed',
    };
    return map[status] || status;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      <div className="w-80 border-r border-gray-200 dark:border-gray-700 flex flex-col bg-white dark:bg-gray-800">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-900 dark:text-white">Knowledge Bases</h2>
            <button
              onClick={() => setShowCreateModal(true)}
              className="p-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700"
            >
              <Plus size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading && knowledgeBases.length === 0 ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="animate-spin text-gray-400" size={24} />
            </div>
          ) : knowledgeBases.length === 0 ? (
            <div className="text-center py-8 px-4">
              <FileText className="mx-auto text-gray-300 dark:text-gray-600 mb-3" size={48} />
              <p className="text-gray-500 dark:text-gray-400 text-sm">
                No knowledge bases yet
              </p>
              <button
                onClick={() => setShowCreateModal(true)}
                className="mt-3 text-blue-600 dark:text-blue-400 text-sm hover:underline"
              >
                Create your first knowledge base
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-700">
              {knowledgeBases.map((kb) => (
                <li
                  key={kb.id}
                  className={clsx(
                    'p-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700',
                    selectedKb?.id === kb.id && 'bg-blue-50 dark:bg-blue-900/20'
                  )}
                  onClick={() => {
                    setSelectedKb(kb);
                  }}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-gray-900 dark:text-white truncate">
                          {kb.name}
                        </p>
                        {roleBadge(kb.role)}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                        {kb.description || 'No description'}
                      </p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-400 dark:text-gray-500">
                        <span>{kb.doc_count ?? 0} docs</span>
                        <span>•</span>
                        <span>{kb.member_count ?? 0} members</span>
                      </div>
                    </div>
                    {(ROLE_LEVEL[kb.role || 'viewer'] ?? 1) >= ROLE_LEVEL.owner ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteKB(kb);
                        }}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                        title="Delete knowledge base"
                      >
                        <Trash2 size={14} />
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900">
        {!selectedKb ? (
          <div className="flex-1 flex items-center justify-center animate-fade-in">
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/10 text-blue-500 dark:text-blue-400 mb-4">
                <FileText size={40} />
              </div>
              <p className="text-gray-600 dark:text-gray-300 font-medium">
                从左侧选择一个知识库
              </p>
              <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">
                查看文档、上传新文件或管理成员
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="p-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        {selectedKb.name}
                      </h3>
                      {roleBadge(currentRole)}
                    </div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {documents.length} document{documents.length !== 1 ? 's' : ''}
                      {' • '}{selectedKb.doc_count ?? 0} total • {selectedKb.member_count ?? 0} member{selectedKb.member_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {canManage && (
                    <button
                      onClick={handleOpenMembers}
                      className="px-4 py-2 text-gray-700 dark:text-gray-200 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-2"
                      title="Manage members"
                    >
                      <Users size={16} />
                      Members
                    </button>
                  )}
                  {canEdit && (
                    <>
                      <label className="px-4 py-2 bg-blue-600 text-white rounded-lg cursor-pointer hover:bg-blue-700 flex items-center gap-2">
                        <Upload size={16} />
                        Upload
                        <input
                          type="file"
                          multiple
                          className="hidden"
                          onChange={handleFileUpload}
                          disabled={isUploading}
                          accept=".pdf,.docx,.md,.markdown,.html,.htm,.txt,.csv"
                        />
                      </label>
                      <button
                        onClick={() => fetchDocuments(selectedKb.id)}
                        className="p-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                      >
                        <RefreshCw size={18} className={clsx(isLoading && 'animate-spin')} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>

            {error && (
              <div className="mx-4 mt-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <div
              className={clsx(
                'flex-1 overflow-y-auto p-4 relative transition-colors',
                isDragging && 'bg-blue-50/60 dark:bg-blue-900/10'
              )}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {isDragging && (
                <div className="absolute inset-3 z-10 pointer-events-none flex items-center justify-center rounded-xl border-2 border-dashed border-blue-400 bg-blue-50/80 dark:bg-blue-900/30 animate-fade-in">
                  <p className="text-sm font-medium text-blue-600 dark:text-blue-300">
                    松开以上传文件
                  </p>
                </div>
              )}
              {isUploading && (
                <div className="mb-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg flex items-center gap-3 animate-fade-in">
                  <Loader2 className="animate-spin text-blue-500" size={20} />
                  <span className="text-blue-700 dark:text-blue-300">正在上传并排队处理…</span>
                </div>
              )}

              {documents.length === 0 ? (
                <div className="text-center py-12">
                  <div className="mx-auto flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/10 text-blue-500 dark:text-blue-400 mb-4">
                    <FileText size={30} />
                  </div>
                  {canEdit ? (
                    <>
                      <p className="text-gray-600 dark:text-gray-300 font-medium">
                        拖拽文件到此处，或点击右上角上传
                      </p>
                      <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">
                        支持 PDF / DOCX / Markdown / HTML / TXT / CSV
                      </p>
                    </>
                  ) : (
                    <p className="text-gray-500 dark:text-gray-400">
                      该知识库还没有文档
                    </p>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {documents.map((doc) => (
                    <div
                      key={doc.id}
                      className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 hover:shadow-soft transition-shadow animate-fade-in"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="flex-shrink-0 w-10 h-10 bg-gray-100 dark:bg-gray-700 rounded-lg flex items-center justify-center">
                            <FileText
                              size={20}
                              className="text-gray-500 dark:text-gray-400"
                            />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="font-medium text-gray-900 dark:text-white truncate">
                              {doc.filename}
                            </p>
                            <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                              <span>{formatFileSize(doc.file_size)}</span>
                              <span>•</span>
                              <span className="flex items-center gap-1">
                                {getStatusIcon(doc.status)}
                                {getStatusText(doc.status)}
                              </span>
                              {doc.chunk_count > 0 && (
                                <>
                                  <span>•</span>
                                  <span>{doc.chunk_count} chunks</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          {canEdit && doc.status === 'failed' && (
                            <button
                              onClick={() => retryDocument(selectedKb.id, doc.id)}
                              className="p-2 text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
                              title="Retry"
                            >
                              <RefreshCw size={16} />
                            </button>
                          )}
                          {canEdit && (
                            <button
                              onClick={() => deleteDocument(selectedKb.id, doc.id)}
                              className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                              title="Delete"
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                        </div>
                      </div>
                      {doc.status === 'processing' && doc.progress > 0 && (
                        <div className="mt-3">
                          <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-blue-500 transition-all duration-300"
                              style={{ width: `${doc.progress}%` }}
                            />
                          </div>
                        </div>
                      )}
                      {doc.status === 'failed' && doc.error && (
                        <p className="mt-2 text-xs text-red-500 dark:text-red-400">
                          Error: {doc.error}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Create Knowledge Base
            </h3>
            <form onSubmit={handleCreateKB} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  required
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                  placeholder="My Knowledge Base"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={newKbDesc}
                  onChange={(e) => setNewKbDesc(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                  placeholder="Optional description..."
                />
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading || !newKbName.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {isLoading && <Loader2 className="animate-spin" size={16} />}
                  Create
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showMembersModal && selectedKb && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Members · {selectedKb.name}
              </h3>
              <button
                onClick={() => setShowMembersModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded"
                title="Close"
              >
                <XCircle size={20} />
              </button>
            </div>

            {/* Add member form */}
            <form onSubmit={handleAddMember} className="flex items-center gap-2 mb-4">
              <div className="flex-1">
                <input
                  type="email"
                  required
                  value={memberEmail}
                  onChange={(e) => setMemberEmail(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white text-sm"
                  placeholder="user@example.com"
                />
              </div>
              <select
                value={memberRole}
                onChange={(e) => setMemberRole(e.target.value as 'editor' | 'viewer')}
                className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white text-sm"
              >
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
              </select>
              <button
                type="submit"
                disabled={isLoading || !memberEmail.trim()}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 text-sm"
              >
                <UserPlus size={16} />
                Add
              </button>
            </form>

            {/* Member list */}
            <div className="max-h-80 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-700">
              {members.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
                  No members yet.
                </p>
              ) : (
                members.map((member) => (
                  <div key={member.user_id} className="flex items-center justify-between py-2.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="flex-shrink-0 w-8 h-8 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                        <Users size={14} className="text-gray-500 dark:text-gray-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {member.user_id === currentUser?.id ? '你' : (member.email || member.user_id)}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">{member.role}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {member.role !== 'owner' && (
                        <>
                          <select
                            value={member.role}
                            onChange={(e) => handleChangeRole(member, e.target.value)}
                            className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                          >
                            <option value="viewer">Viewer</option>
                            <option value="editor">Editor</option>
                            <option value="owner">Owner</option>
                          </select>
                          <button
                            onClick={() => handleRemoveMember(member)}
                            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded ml-1"
                            title="Remove member"
                          >
                            <Trash2 size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ManagePage;
