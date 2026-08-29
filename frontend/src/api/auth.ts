import apiClient from './client';
import { TokenResponse, User } from '../types';

export const authApi = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const { data } = await apiClient.post('/api/auth/login', { email, password });
    return data;
  },

  async register(email: string, password: string): Promise<User> {
    const { data } = await apiClient.post('/api/auth/register', { email, password });
    return data;
  },

  async refresh(refreshToken: string): Promise<TokenResponse> {
    const { data } = await apiClient.post('/api/auth/refresh', {
      refresh_token: refreshToken,
    });
    return data;
  },

  async logout(refreshToken?: string): Promise<void> {
    if (refreshToken) {
      await apiClient.post('/api/auth/logout', { refresh_token: refreshToken }).catch(() => {});
    }
  },

  async getMe(): Promise<User> {
    const { data } = await apiClient.get('/api/auth/me');
    return data;
  },
};
