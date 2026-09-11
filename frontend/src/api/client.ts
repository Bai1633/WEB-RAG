import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor: add auth token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor: handle 401 and token refresh
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: unknown) => void;
  reject: (reason?: any) => void;
}> = [];

// Backend validation messages that deserve a Chinese wording in the UI.
const VALIDATION_MESSAGE_MAP: Record<string, string> = {
  'Password must contain at least one lowercase letter': '密码需包含至少一个小写字母',
  'Password must contain at least one uppercase letter': '密码需包含至少一个大写字母',
  'Password must contain at least one digit': '密码需包含至少一个数字',
};

/**
 * FastAPI returns HTTP 422 with `detail` as an ARRAY of validation errors:
 *   { detail: [{ loc: [...], msg: "Value error, Password must ...", ... }] }
 *
 * Callers (authStore etc.) read `error.response.data.detail` as a plain string,
 * so an array either renders as nothing or throws "Objects are not valid as a
 * React child". Normalize it into one readable line before it reaches any UI.
 */
const normalizeValidationDetail = (detail: unknown): string => {
  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item: any) => {
        const raw = typeof item === 'string' ? item : item?.msg ?? '';
        const cleaned = String(raw).replace(/^Value error,\s*/, '');
        return VALIDATION_MESSAGE_MAP[cleaned] ?? cleaned;
      })
      .filter(Boolean)
      .join('；');
  }

  if (detail && typeof detail === 'object') {
    return String((detail as any).msg ?? '');
  }

  return String(detail ?? '');
};

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Normalize 422 `detail` arrays so callers always receive a string.
    const data = error.response?.data;
    if (data && typeof data === 'object' && Array.isArray(data.detail)) {
      data.detail = normalizeValidationDetail(data.detail);
    }

    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise(function (resolve, reject) {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return apiClient(originalRequest);
          })
          .catch((err) => {
            return Promise.reject(err);
          });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('refresh_token');

      if (!refreshToken) {
        isRefreshing = false;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.dispatchEvent(new CustomEvent('auth:logout'));
        return Promise.reject(error);
      }

      try {
        const response = await axios.post(
          `${BASE_URL}/api/auth/refresh`,
          { refresh_token: refreshToken }
        );
        const { access_token, refresh_token } = response.data;

        localStorage.setItem('access_token', access_token);
        localStorage.setItem('refresh_token', refresh_token);

        apiClient.defaults.headers.common.Authorization = `Bearer ${access_token}`;
        originalRequest.headers.Authorization = `Bearer ${access_token}`;

        processQueue(null, access_token);
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.dispatchEvent(new CustomEvent('auth:logout'));
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default apiClient;
