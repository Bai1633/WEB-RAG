import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Coins,
  FileText,
  Layers,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { statsApi, UserStats } from '../api/stats';
import { useKBStore } from '../stores/kbStore';
import { clsx } from 'clsx';

const formatNumber = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
};

const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent: string;
  delay?: string;
}> = ({ icon, label, value, sub, accent, delay }) => (
  <div
    className="card p-5 flex items-start gap-4 hover:shadow-soft-lg transition-shadow animate-fade-in-up"
    style={{ animationDelay: delay }}
  >
    <span className={clsx('flex items-center justify-center w-11 h-11 rounded-xl text-white flex-shrink-0', accent)}>
      {icon}
    </span>
    <div className="min-w-0">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-white leading-tight mt-0.5">
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{sub}</p>}
    </div>
  </div>
);

const StatsPage: React.FC = () => {
  const { knowledgeBases, fetchKnowledgeBases } = useKBStore();
  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [s] = await Promise.all([statsApi.get(), fetchKnowledgeBases()]);
      setStats(s);
    } catch (err: any) {
      setError(err.response?.data?.detail || '加载统计数据失败');
    } finally {
      setIsLoading(false);
    }
  }, [fetchKnowledgeBases]);

  useEffect(() => {
    void load();
  }, [load]);

  const docs = stats?.documents;
  const completedPct = docs && docs.total > 0 ? (docs.completed / docs.total) * 100 : 0;
  const inFlightPct = docs && docs.total > 0 ? (docs.in_flight / docs.total) * 100 : 0;
  const failedPct = docs && docs.total > 0 ? (docs.failed / docs.total) * 100 : 0;

  return (
    <div className="h-[calc(100vh-4rem)] overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6">
        {/* Page header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">数据看板</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              你的知识库与问答使用概览
            </p>
          </div>
          <button
            onClick={load}
            className="btn-secondary !px-3"
            title="刷新"
            disabled={isLoading}
          >
            <RefreshCw size={16} className={clsx(isLoading && 'animate-spin')} />
          </button>
        </div>

        {isLoading && !stats ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="animate-spin text-gray-400" size={32} />
          </div>
        ) : error ? (
          <div className="card p-8 text-center text-sm text-red-500">{error}</div>
        ) : stats ? (
          <>
            {/* Stat cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <StatCard
                icon={<BookOpen size={20} />}
                label="知识库"
                value={formatNumber(stats.knowledge_bases)}
                sub="你有权限访问的库"
                accent="bg-gradient-to-br from-blue-500 to-indigo-600"
              />
              <StatCard
                icon={<FileText size={20} />}
                label="文档总数"
                value={formatNumber(docs?.total ?? 0)}
                sub={`${docs?.completed ?? 0} 个已就绪`}
                accent="bg-gradient-to-br from-cyan-500 to-blue-600"
                delay="60ms"
              />
              <StatCard
                icon={<Layers size={20} />}
                label="向量分块"
                value={formatNumber(stats.chunks)}
                sub="已入库的可检索单元"
                accent="bg-gradient-to-br from-violet-500 to-purple-600"
                delay="120ms"
              />
              <StatCard
                icon={<MessageSquare size={20} />}
                label="问答轮次"
                value={formatNumber(stats.chat_rounds)}
                sub={`累计 ${formatNumber(stats.total_tokens)} tokens`}
                accent="bg-gradient-to-br from-emerald-500 to-teal-600"
                delay="180ms"
              />
            </div>

            {/* Document status breakdown */}
            <div className="card p-6 mt-6 animate-fade-in-up" style={{ animationDelay: '220ms' }}>
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-semibold text-gray-900 dark:text-white">文档处理状态</h2>
                {docs && docs.total > 0 && (
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    共 {docs.total} 个文档
                  </span>
                )}
              </div>

              {docs && docs.total > 0 ? (
                <>
                  {/* Stacked bar */}
                  <div className="h-3 w-full rounded-full overflow-hidden flex bg-gray-100 dark:bg-gray-700">
                    <div
                      className="bg-gradient-to-r from-emerald-400 to-teal-500 transition-all duration-500"
                      style={{ width: `${completedPct}%` }}
                    />
                    <div
                      className="bg-gradient-to-r from-blue-400 to-indigo-500 transition-all duration-500"
                      style={{ width: `${inFlightPct}%` }}
                    />
                    <div
                      className="bg-gradient-to-r from-orange-400 to-red-500 transition-all duration-500"
                      style={{ width: `${failedPct}%` }}
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-4 mt-4">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 size={16} className="text-emerald-500" />
                      <div>
                        <p className="text-sm font-semibold text-gray-900 dark:text-white">
                          {docs.completed}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">已完成</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Loader2 size={16} className="text-blue-500 animate-spin" />
                      <div>
                        <p className="text-sm font-semibold text-gray-900 dark:text-white">
                          {docs.in_flight}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">处理中 / 排队</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <AlertTriangle size={16} className="text-orange-500" />
                      <div>
                        <p className="text-sm font-semibold text-gray-900 dark:text-white">
                          {docs.failed}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">失败（可重试）</p>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-400 dark:text-gray-500 py-4 text-center">
                  暂无文档，去知识库管理页上传第一个文档吧
                </p>
              )}
            </div>

            {/* Knowledge base quick access */}
            <div className="card p-6 mt-6 animate-fade-in-up" style={{ animationDelay: '260ms' }}>
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-semibold text-gray-900 dark:text-white">快速进入问答</h2>
                <Link
                  to="/manage"
                  className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                >
                  <Plus size={12} />
                  新建知识库
                </Link>
              </div>

              {knowledgeBases.length === 0 ? (
                <p className="text-sm text-gray-400 dark:text-gray-500 py-4 text-center">
                  还没有知识库
                </p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {knowledgeBases.map((kb) => (
                    <Link
                      key={kb.id}
                      to={`/kb/${kb.id}/chat`}
                      className="group flex items-center gap-3 p-3 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:shadow-soft transition-all"
                    >
                      <span className="flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500/10 to-indigo-500/10 text-blue-600 dark:text-blue-400 group-hover:from-blue-500 group-hover:to-indigo-600 group-hover:text-white transition-all">
                        <BookOpen size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {kb.name}
                        </p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">
                          {kb.doc_count ?? 0} 文档 · {(kb.embed_dim ?? 0)}d
                        </p>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>

            {/* Token footnote */}
            <div className="flex items-center gap-2 mt-6 text-xs text-gray-400 dark:text-gray-500 animate-fade-in" style={{ animationDelay: '300ms' }}>
              <Coins size={12} />
              tokens 为按 cl100k_base 近似估算的累计消耗（含提问与回答）
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default StatsPage;
