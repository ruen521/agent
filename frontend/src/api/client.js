import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const apiKey = import.meta.env.VITE_API_KEY;

export const api = axios.create({
  baseURL,
  headers: {
    "x-request-id": crypto.randomUUID(),
    ...(apiKey ? { "x-api-key": apiKey } : {})
  }
});

export async function fetchAgents() {
  const { data } = await api.get("/agents/list");
  return data.agents || [];
}

export async function fetchStats() {
  const { data } = await api.get("/agents/stats");
  return data;
}

export async function fetchRisks(limit = 100) {
  const { data } = await api.get("/data/risks", { params: { limit } });
  return data.risks || [];
}

export async function fetchInventory(queryType = "all", limit = 100) {
  const { data } = await api.get("/data/inventory", {
    params: { query_type: queryType, limit }
  });
  return data.items || [];
}

export async function invokeAgent(payload) {
  const { data } = await api.post("/agents/invoke", payload);
  return data;
}
