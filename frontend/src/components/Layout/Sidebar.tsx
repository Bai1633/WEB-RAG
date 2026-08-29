import React, { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  BarChart3,
  BookOpen,
  FileText,
  Plus,
  Settings,
} from 'lucide-react';
import { useKBStore } from '../../stores/kbStore';
import { clsx } from 'clsx';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const NAV_ITEMS = [
  { to: '/stats', icon: BarChart3, label: '数据看板' },
  { to: '/manage', icon: Settings, label: '知识库管理' },
];

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  const { knowledgeBases, fetchKnowledgeBases, setCurrentKB } = useKBStore();
  const location = useLocation();

  useEffect(() => {
    fetchKnowledgeBases();
  }, [fetchKnowledgeBases]);

  const isActive = (kbId: string) => {
    return location.pathname.includes(kbId);
  };

  const handleSelectKB = (kb: (typeof knowledgeBases)[number]) => {
    setCurrentKB(kb);
    onClose();
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden animate-fade-in"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed lg:static top-16 left-0 h-[calc(100vh-4rem)] w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 z-30 transform transition-transform duration-300 flex flex-col',
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        )}
      >
        {/* Navigation */}
        <nav className="p-3 border-b border-gray-100 dark:border-gray-700 space-y-1">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <Link
              key={to}
              to={to}
              onClick={onClose}
              className={clsx(
                'flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
                location.pathname === to
                  ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
              )}
            >
              <Icon size={16} />
              {label}
            </Link>
          ))}
        </nav>

        {/* Knowledge base list */}
        <div className="flex-1 overflow-y-auto">
          <div className="flex items-center justify-between px-4 pt-4 pb-2">
            <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
              知识库
            </h2>
            <Link
              to="/manage"
              onClick={onClose}
              className="p-1 rounded text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
              title="新建知识库"
            >
              <Plus size={14} />
            </Link>
          </div>

          <div className="px-2 pb-2">
            {knowledgeBases.length === 0 ? (
              <div className="px-3 py-6 text-center">
                <BookOpen size={24} className="mx-auto text-gray-300 dark:text-gray-600 mb-2" />
                <p className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                  还没有知识库
                  <br />
                  到管理页创建一个吧
                </p>
              </div>
            ) : (
              <nav className="space-y-0.5">
                {knowledgeBases.map((kb) => (
                  <Link
                    key={kb.id}
                    to={`/kb/${kb.id}/chat`}
                    onClick={() => handleSelectKB(kb)}
                    className={clsx(
                      'group flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-colors',
                      isActive(kb.id)
                        ? 'bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/25 dark:to-indigo-900/20 text-blue-600 dark:text-blue-400 font-medium'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                    )}
                  >
                    <BookOpen
                      size={15}
                      className={clsx(
                        'flex-shrink-0',
                        isActive(kb.id) ? 'text-blue-500' : 'text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-300'
                      )}
                    />
                    <span className="truncate flex-1">{kb.name}</span>
                    {(kb.doc_count ?? 0) > 0 && (
                      <span className="flex items-center gap-0.5 text-[10px] text-gray-400 dark:text-gray-500 flex-shrink-0">
                        <FileText size={10} />
                        {kb.doc_count}
                      </span>
                    )}
                  </Link>
                ))}
              </nav>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-100 dark:border-gray-700">
          <p className="text-[11px] text-gray-400 dark:text-gray-500 text-center">
            RAG Knowledge Base QA
          </p>
        </div>
      </aside>
    </>
  );
};
