import axios from "axios";

export const TOKEN_KEY = "sentinelle_token";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Attach the JWT to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, drop the token and bounce to the login page
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

// --- Auth ---
export const login = (email: string, password: string) =>
  api.post("/auth/login", { email, password }).then((r) => r.data as { access_token: string; token_type: string });
export const getMe = () =>
  api.get("/auth/me").then((r) => r.data as { id: number; email: string; full_name?: string; role: string });

// --- Campaigns ---
export const getCampaigns = () => api.get("/campaigns/").then((r) => r.data);
export const getCampaign  = (id: number) => api.get(`/campaigns/${id}`).then((r) => r.data);
export const createCampaign = (data: object) => api.post("/campaigns/", data).then((r) => r.data);
export const updateCampaign = (id: number, data: object) => api.patch(`/campaigns/${id}`, data).then((r) => r.data);
export const deleteCampaign = (id: number) => api.delete(`/campaigns/${id}`);
export const suggestKeywords = (id: number) => api.post(`/campaigns/${id}/suggest-keywords`).then((r) => r.data);
export const suggestNewKeywords = (data: object) => api.post("/campaigns/suggest-new", data).then((r) => r.data);

// --- Creators ---
export const getCreators       = () => api.get("/creators/").then((r) => r.data);
export const getCreator        = (id: number) => api.get(`/creators/${id}`).then((r) => r.data);
export const addCreator        = (data: object) => api.post("/creators/", data).then((r) => r.data);
export const deleteCreator     = (id: number) => api.delete(`/creators/${id}`);
export const refreshCreator    = (id: number) => api.post(`/creators/${id}/refresh`).then((r) => r.data);
export const resetCreator      = (id: number) => api.post(`/creators/${id}/reset`);
export const stopCreator       = (id: number) => api.post(`/creators/${id}/stop`);
export const finalizeCreator   = (id: number) => api.post(`/creators/${id}/finalize`).then((r) => r.data);
export const restartCreator    = (id: number) => api.post(`/creators/${id}/restart`).then((r) => r.data);
export const getCreatorPosts   = (id: number) => api.get(`/creators/${id}/posts`).then((r) => r.data);
export const updateCreator = (id: number, data: any) => api.patch(`/creators/${id}`, data).then((r) => r.data);
export const getCreatorComments = (id: number, sentiment?: string, sort?: string) =>
  api.get(`/creators/${id}/comments`, { params: { ...(sentiment ? { sentiment } : {}), ...(sort ? { sort } : {}) } }).then((r) => r.data);
export const getTopComments = (id: number) => api.get(`/creators/${id}/top-comments`).then((r) => r.data);
export const recomputeTopics = (id: number) => api.post(`/creators/${id}/recompute-topics`).then((r) => r.data);
export const summarizePost = (creatorId: number, postId: number) =>
  api.post(`/creators/${creatorId}/posts/${postId}/summary`).then((r) => r.data);
export const getPostTopics = (creatorId: number, postId: number) =>
  api.get(`/creators/${creatorId}/posts/${postId}/topics`).then((r) => r.data);
export const getPostComments = (creatorId: number, postId: number, params?: { sentiment?: string; sort?: string; limit?: number; offset?: number }) =>
  api.get(`/creators/${creatorId}/posts/${postId}/comments`, { params }).then((r) => r.data);
export const rescrapePost = (creatorId: number, postId: number) =>
  api.post(`/creators/${creatorId}/posts/${postId}/rescrape`).then((r) => r.data);

// --- Analytics ---
export const getMetrics          = (campaignId: number) => api.get(`/analytics/${campaignId}/metrics`).then((r) => r.data);
export const computeMetrics      = (campaignId: number, period = "weekly") =>
  api.post(`/analytics/${campaignId}/compute`, null, { params: { period } }).then((r) => r.data);
export const getTopics             = (campaignId: number) => api.get(`/analytics/${campaignId}/topics`).then((r) => r.data);
export const getCommentTimeline    = (campaignId: number) => api.get(`/analytics/${campaignId}/comment-timeline`).then((r) => r.data);
export const getSentimentTimeline  = (campaignId: number) =>
  api.get(`/dashboard/sentiment-timeline/${campaignId}`).then((r) => r.data);

// --- Dashboard ---
export const getOverview = () => api.get("/dashboard/overview").then((r) => r.data);

// --- Reports ---
export const getReports      = () => api.get("/reports/").then((r) => r.data);
export const generateReport  = (data: object) => api.post("/reports/generate", data).then((r) => r.data);
export const getReport       = (id: number) => api.get(`/reports/${id}`).then((r) => r.data);

// --- Matching ---
export const matchCreators = (campaignId: number, topK = 10) =>
  api.get(`/matching/${campaignId}`, { params: { top_k: topK } }).then((r) => r.data);
export const computeEmbeddings = (force = false) =>
  api.post("/matching/compute-embeddings", null, { params: { force } }).then((r) => r.data);
export const refreshAllMatches = () =>
  api.post("/matching/refresh-all").then((r) => r.data);
export const checkEmbeddingBackend = () =>
  api.get("/matching/embedding-backend").then((r) => r.data);

// --- Comments ---
export const getComments = (campaignId: number, sentiment?: string, sort?: string) =>
  api.get("/comments/", { params: { campaign_id: campaignId, ...(sentiment ? { sentiment } : {}), ...(sort ? { sort } : {}) } }).then((r) => r.data);

// --- Pipeline Debug ---
export const getPipelineStatus = () => api.get("/pipeline/status").then((r) => r.data);
export const getCreatorLogs   = (id: number) => api.get(`/pipeline/logs/${id}`).then((r) => r.data);

export default api;
