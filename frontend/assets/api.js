/**
 * @file api.js
 * @description MongoFleet — API client. Centralizes all backend calls to ensure consistent
 *              authentication and error handling across all pages. Interacts with real backend routes.
 * @author Madan U <madanu135@gmail.com>
 * @date 2026-09-17
 */

// MongoFleet — API client
// All calls go through here so every page handles auth/errors the same way.
// No mock data, no simulated responses — every function hits a real backend route.

const Api = (() => {
  async function request(path, options = {}) {
    const res = await fetch(path, {
      method: options.method || "GET",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      credentials: "same-origin",
      body: options.body ? JSON.stringify(options.body) : undefined,
    });

    if (res.status === 401) {
      if (!location.pathname.endsWith("login.html")) {
        location.href = "login.html";
      }
      throw new Error("authentication_required");
    }

    let data = null;
    try { data = await res.json(); } catch (_e) { /* no body */ }

    if (!res.ok) {
      const message = (data && data.error) || `Request failed (${res.status})`;
      const err = new Error(message);
      err.status = res.status;
      err.data = data;   // structured payload (e.g. {requires_confirmation, warning}) — callers can inspect this
      throw err;
    }
    return data;
  }

  return {
    login: (username, password) => request("/api/auth/login", { method: "POST", body: { username, password } }),
    logout: () => request("/api/auth/logout", { method: "POST" }),
    me: () => request("/api/auth/me"),

    dashboardSummary: () => request("/api/dashboard/summary"),

    listServers: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/inventory/servers${qs ? `?${qs}` : ""}`);
    },
    getServer: (id) => request(`/api/inventory/servers/${id}`),
    createServer: (payload) => request("/api/inventory/servers", { method: "POST", body: payload }),
    testConnectivity: (id) => request(`/api/inventory/servers/${id}/test-connectivity`, { method: "POST" }),
    refreshHealth: (id) => request(`/api/inventory/servers/${id}/refresh-health`, { method: "POST" }),
    getLiveMetrics: (id) => request(`/api/inventory/servers/${id}/live-metrics`),

    listAlerts: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/alerts${qs ? `?${qs}` : ""}`);
    },
    alertsSummary: () => request("/api/alerts/summary"),
    pollAlertsNow: () => request("/api/alerts/poll", { method: "POST" }),

    runOperation: (operation_type, server_id, params = {}, force = false) =>
      request("/api/operations", { method: "POST", body: { operation_type, server_id, params, force } }),
    listOperations: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/operations${qs ? `?${qs}` : ""}`);
    },
    getOperation: (id) => request(`/api/operations/${id}`),

    listSchedules: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/operations/schedules${qs ? `?${qs}` : ""}`);
    },
    createSchedule: (payload) => request("/api/operations/schedules", { method: "POST", body: payload }),
    editSchedule: (id, payload) => request(`/api/operations/schedules/${id}`, { method: "PATCH", body: payload }),
    cancelSchedule: (id) => request(`/api/operations/schedules/${id}`, { method: "DELETE" }),

    getLongRunningThreshold: () => request("/api/operations/settings/long-running-threshold"),
    setLongRunningThreshold: (minutes) =>
      request("/api/operations/settings/long-running-threshold", { method: "PATCH", body: { threshold_minutes: minutes } }),

    getPerformanceAdvisor: (serverId, timeframe) =>
      request(`/api/monitoring/performance-advisor/${serverId}?timeframe=${encodeURIComponent(timeframe)}`),
    getMonitoringDashboardStats: () => request("/api/monitoring/dashboard-stats"),

    listAudit: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/audit${qs ? `?${qs}` : ""}`);
    },
    auditExportUrl: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return `/api/audit/export${qs ? `?${qs}` : ""}`;
    },

    // Sends {username, email, issue, page} to the backend, which is expected
    // to persist the ticket (optional) and email the DBA team.
    submitSupportRequest: (payload) => request("/api/support/tickets", { method: "POST", body: payload }),

    // Change history for a scheduled operation (audit trail) — populated by
    // PATCH /api/operations/schedules/:id storing {comment, change_summary}.
    getScheduleHistory: (id) => request(`/api/operations/schedules/${id}/history`),
  };
})();


