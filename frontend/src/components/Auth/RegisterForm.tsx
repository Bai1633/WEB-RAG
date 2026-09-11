import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2, UserPlus } from 'lucide-react';
import { useAuthStore } from '../../stores/authStore';
import { AuthLayout } from './AuthLayout';

export const RegisterForm: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [localError, setLocalError] = useState('');
  const { register, isLoading, error, clearError } = useAuthStore();
  const navigate = useNavigate();

  // Mirrors backend rule in backend/app/schemas/auth.py (min 8, lower, upper, digit)
  const passwordRules = [
    { label: '至少 8 位', passed: password.length >= 8 },
    { label: '含小写字母', passed: /[a-z]/.test(password) },
    { label: '含大写字母', passed: /[A-Z]/.test(password) },
    { label: '含数字', passed: /\d/.test(password) },
  ];
  const passwordValid = passwordRules.every((r) => r.passed);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    setLocalError('');

    if (!passwordValid) {
      setLocalError(
        '密码不符合要求：' + passwordRules.filter((r) => !r.passed).map((r) => r.label).join('、')
      );
      return;
    }

    if (password !== confirmPassword) {
      return;
    }

    try {
      await register(email, password);
      navigate('/');
    } catch {
      // Error is handled by store
    }
  };

  const passwordsMatch = password === confirmPassword;

  return (
    <AuthLayout
      title="创建账号"
      subtitle={
        <>
          已有账号？{' '}
          <Link to="/login" className="text-blue-600 dark:text-blue-400 hover:underline">
            直接登录
          </Link>
        </>
      }
    >
      <form className="space-y-5" onSubmit={handleSubmit}>
        {(error || localError) && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg text-sm animate-fade-in">
            {localError || error}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              邮箱
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field mt-1.5"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              密码
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              className="input-field mt-1.5"
              placeholder="至少 8 位，含大小写字母与数字"
              onChange={(e) => {
                setPassword(e.target.value);
                setLocalError('');
              }}
            />
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {passwordRules.map((rule) => (
                <span
                  key={rule.label}
                  className={`text-xs ${
                    rule.passed
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-gray-400 dark:text-gray-500'
                  }`}
                >
                  {rule.passed ? '✓' : '○'} {rule.label}
                </span>
              ))}
            </div>
          </div>

          <div>
            <label
              htmlFor="confirmPassword"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              确认密码
            </label>
            <input
              id="confirmPassword"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className={`input-field mt-1.5 ${
                confirmPassword && !passwordsMatch
                  ? 'border-red-500 focus:ring-red-500/60'
                  : ''
              }`}
              placeholder="再次输入密码"
            />
            {confirmPassword && !passwordsMatch && (
              <p className="mt-1 text-sm text-red-600 dark:text-red-400 animate-fade-in">
                两次输入的密码不一致
              </p>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={isLoading || !passwordsMatch}
          className="btn-primary w-full"
        >
          {isLoading ? (
            <Loader2 className="animate-spin" size={18} />
          ) : (
            <UserPlus size={18} />
          )}
          {isLoading ? '创建中…' : '注册'}
        </button>
      </form>
    </AuthLayout>
  );
};
