import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

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
export const restartCreator    = (id: number) => api.post(`/creators/${id}/restart`).then((r) => r.data);
export const getCreatorPosts   = (id: number) => api.get(`/creators/${id}/posts`).then((r) => r.data);
export const updateCreator = (id: number, data: any) => api.patch(`/creators/${id}`, data).then((r) => r.data);
export const getCreatorComments = (id: number, sentiment?: string) =>
  api.get(`/creators/${id}/comments`, { params: sentiment ? { sentiment } : {} }).then((r) => r.data);

// --- Analytics ---
export const getMetrics          = (campaignId: number) => api.get(`/analytics/${campaignId}/metrics`).then((r) => r.data);
export const computeMetrics      = (campaignId: number, period = "weekly") =>
  api.post(`/analytics/${campaignId}/compute`, null, { params: { period } }).then((r) => r.data);
export const getTopics           = (campaignId: number) => api.get(`/analytics/${campaignId}/topics`).then((r) => r.data);
export const getSentimentTimeline = (campaignId: number) =>
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
export const computeEmbeddings = () =>
  api.post("/matching/compute-embeddings").then((r) => r.data);

// --- Comments ---
export const getComments = (campaignId: number, sentiment?: string) =>
  api.get("/comments/", { params: { campaign_id: campaignId, ...(sentiment ? { sentiment } : {}) } }).then((r) => r.data);

// --- Pipeline Debug ---
export const getPipelineStatus = () => api.get("/pipeline/status").then((r) => r.data);
export const getCreatorLogs   = (id: number) => api.get(`/pipeline/logs/${id}`).then((r) => r.data);

export default api;
