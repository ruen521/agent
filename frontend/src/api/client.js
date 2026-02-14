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

function parseSseEvent(chunk) {
  const lines = chunk.split("\n");
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) return null;
  const dataText = dataLines.join("\n");
  let data = null;
  try {
    data = JSON.parse(dataText);
  } catch (error) {
    data = { raw: dataText };
  }
  return { event, data };
}

export async function invokeAgentStream(payload, handlers = {}) {
  const headers = {
    "Content-Type": "application/json",
    "x-request-id": crypto.randomUUID(),
    ...(apiKey ? { "x-api-key": apiKey } : {})
  };
  const response = await fetch(`${baseURL}/agents/invoke_stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal: handlers.signal
  });
  if (!response.ok || !response.body) {
    throw new Error(`STREAM_HTTP_${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes("\n\n")) {
      const boundary = buffer.indexOf("\n\n");
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseEvent(rawEvent);
      if (!parsed) continue;

      if (parsed.event === "start") {
        handlers.onStart?.(parsed.data);
        continue;
      }
      if (parsed.event === "update") {
        handlers.onUpdate?.(parsed.data);
        continue;
      }
      if (parsed.event === "done") {
        donePayload = parsed.data;
        handlers.onDone?.(parsed.data);
        continue;
      }
      if (parsed.event === "error") {
        handlers.onError?.(parsed.data);
        const reason = parsed.data?.error_message || parsed.data?.message || parsed.data?.error_code || parsed.data?.code || "STREAM_ERROR";
        throw new Error(reason);
      }
    }
  }

  if (!donePayload) {
    throw new Error("STREAM_DONE_MISSING");
  }
  return donePayload;
}

export async function createExportJob(payload) {
  const { data } = await api.post("/reports/exports", payload);
  return data;
}

export async function getExportJob(jobId) {
  const { data } = await api.get(`/reports/exports/${jobId}`);
  return data;
}

function extractFilename(contentDisposition, fallbackName) {
  if (!contentDisposition) return fallbackName;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (error) {
      return utf8Match[1];
    }
  }
  const basicMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  return basicMatch?.[1] || fallbackName;
}

function extensionFromContentType(contentType) {
  const normalized = String(contentType || "").toLowerCase();
  if (normalized.includes("application/pdf")) return ".pdf";
  if (normalized.includes("spreadsheetml.sheet")) return ".xlsx";
  return "";
}

export async function downloadExport(jobId) {
  const response = await api.get(`/reports/exports/${jobId}/download`, {
    responseType: "blob"
  });
  const fallbackName = `export_${jobId}${extensionFromContentType(response.headers?.["content-type"])}`;
  const filename = extractFilename(
    response.headers?.["content-disposition"],
    fallbackName
  );
  return { blob: response.data, filename };
}
