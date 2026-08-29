import React from 'react';
import { BookOpen, FileSearch, Quote, ShieldCheck } from 'lucide-react';

const FEATURES = [
  {
    icon: FileSearch,
    title: '混合检索',
    desc: '向量 + 关键词 + 全文三路召回，RRF 融合与 BGE 重排',
  },
  {
    icon: Quote,
    title: '引用溯源',
    desc: '每个回答标注来源文件与相关度，可展开查看原文片段',
  },
  {
    icon: ShieldCheck,
    title: '私有化部署',
    desc: '数据不出域，多租户知识库与角色权限隔离',
  },
];

interface AuthLayoutProps {
  title: string;
  subtitle: React.ReactNode;
  children: React.ReactNode;
}

/** Split-screen shell shared by the login / register pages:
 * brand + feature highlights on the left, the form card on the right. */
export const AuthLayout: React.FC<AuthLayoutProps> = ({ title, subtitle, children }) => (
  <div className="min-h-screen flex bg-gray-50 dark:bg-gray-900">
    {/* Brand panel (desktop only) */}
    <div className="hidden lg:flex lg:w-[46%] relative overflow-hidden bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-700">
      <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-white/10 blur-3xl" />
      <div className="absolute bottom-0 right-0 w-[28rem] h-[28rem] rounded-full bg-white/5 blur-3xl translate-x-1/4 translate-y-1/4" />

      <div className="relative z-10 flex flex-col justify-between p-12 w-full text-white">
        <div className="flex items-center gap-3">
          <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-white/15 backdrop-blur">
            <BookOpen size={22} />
          </span>
          <span className="font-bold text-xl tracking-tight">Knowledge Base QA</span>
        </div>

        <div className="animate-fade-in-up">
          <h1 className="text-3xl font-bold leading-snug mb-3">
            让每一次提问
            <br />
            都有据可依
          </h1>
          <p className="text-white/80 text-sm leading-relaxed max-w-sm mb-10">
            上传文档，系统自动完成解析、分块与向量化入库；
            通过自然语言即时检索知识，并返回带引用来源的回答。
          </p>
          <ul className="space-y-5">
            {FEATURES.map(({ icon: Icon, title: t, desc }) => (
              <li key={t} className="flex items-start gap-3">
                <span className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-lg bg-white/15 backdrop-blur mt-0.5">
                  <Icon size={17} />
                </span>
                <div>
                  <p className="text-sm font-semibold">{t}</p>
                  <p className="text-xs text-white/75 mt-0.5">{desc}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-white/60">RAG · FastAPI · React · pgvector · Celery</p>
      </div>
    </div>

    {/* Form panel */}
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        {/* Mobile brand */}
        <div className="lg:hidden flex items-center justify-center gap-2 mb-8">
          <span className="flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-600 text-white">
            <BookOpen size={18} />
          </span>
          <span className="font-bold text-lg text-gray-900 dark:text-white">
            Knowledge Base QA
          </span>
        </div>

        <div className="card p-8 animate-fade-in-up">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">{title}</h2>
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-6">{subtitle}</div>
          {children}
        </div>
      </div>
    </div>
  </div>
);
