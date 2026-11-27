"use strict";

(() => {
  const button = document.getElementById("agent-context-download");
  if (!button) return;
  const status = document.getElementById("agent-context-status");
  const failures = document.getElementById("agent-context-failures");
  const login = document.getElementById("agent-context-login");
  login.href = "/auth/login?" + new URLSearchParams({ return_to: "/#agent" });
  // Fixed read-only exports. Never expand this list from API data or source links.
  const sources = Object.freeze([
    { name: "catalog", label: "资源目录", url: "/api/export.json" },
    { name: "research_guide", label: "研究分类", url: "/api/research-guide" },
    { name: "library", label: "数据与模型", url: "/api/platform/library" },
    { name: "research", label: "研究成果", url: "/api/platform/research" },
    { name: "workspace_docs", label: "团队文书索引", url: "/api/workspace-docs" },
    { name: "servers", label: "服务器观察", url: "/api/platform/servers" },
    { name: "progress_digest", label: "团队研究全景", url: "/progress/api/progress-digest" },
    { name: "lab_review", label: "团队阶段复盘", url: "/progress/api/lab-review?format=json" },
    { name: "directions", label: "研究方向", url: "/progress/api/directions" },
    { name: "direction_methods", label: "方向方法比较", url: "/progress/api/direction-methods" },
    { name: "literature", label: "文献目录与共享笔记", url: "/papers/api/export" },
    { name: "guide", label: "Agent 使用手册", url: "/docs/agent-guide.md", text: true },
    { name: "contract", label: "机器可读接入约定", url: "/docs/agent-contract.json" },
  ]);
  const sensitiveKeys = new Set(["cookie", "setcookie", "authorization", "proxyauthorization", "authheaders", "accesstoken", "refreshtoken", "idtoken", "sessiontoken", "csrftoken", "apikey", "apisecret", "appsecret", "clientsecret", "password", "token"]);
  const messages = {
    login_required: "需要重新登录", access_denied: "当前无访问权限", unexpected_html: "返回了登录或网页内容",
    invalid_content_type: "返回格式不符", invalid_json: "JSON 内容无法解析", invalid_payload: "未返回有效内容",
    empty_guide: "手册为空", timeout: "读取超时", network_or_redirect: "网络或登录跳转未完成",
  };

  function cleanMetadata(value) {
    if (Array.isArray(value)) return value.map(cleanMetadata);
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).filter(([key]) => !sensitiveKeys.has(key.replace(/[-_]/g, "").toLowerCase())).map(([key, item]) => [key, cleanMetadata(item)]));
    }
    return value;
  }

  async function readSource(source) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    const result = (entry) => ({ url: source.url, fetched_at: new Date().toISOString(), ...entry });
    try {
      const response = await fetch(source.url, {
        method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
        headers: { Accept: source.text ? "text/plain, text/markdown" : "application/json" }, signal: controller.signal,
      });
      if (response.status === 401) return result({ status: "failed", error_code: "login_required" });
      if (response.status === 403) return result({ status: "failed", error_code: "access_denied" });
      if (!response.ok) return result({ status: "failed", error_code: `http_${response.status}` });
      const type = (response.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
      if (type === "text/html" || type === "application/xhtml+xml") return result({ status: "failed", error_code: "unexpected_html" });
      if (source.text) {
        if (!["text/plain", "text/markdown", "text/x-markdown"].includes(type)) return result({ status: "failed", error_code: "invalid_content_type" });
        const data = await response.text();
        if (/^\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b)/i.test(data)) return result({ status: "failed", error_code: "unexpected_html" });
        return data.trim() ? result({ status: "ok", data }) : result({ status: "failed", error_code: "empty_guide" });
      }
      if (type !== "application/json" && !type.endsWith("+json")) return result({ status: "failed", error_code: "invalid_content_type" });
      let data;
      try { data = await response.json(); }
      catch { return result({ status: "failed", error_code: "invalid_json" }); }
      if (!data || typeof data !== "object") return result({ status: "failed", error_code: "invalid_payload" });
      return result({ status: "ok", data: source.name === "contract" ? data : cleanMetadata(data) });
    } catch {
      return result({ status: "failed", error_code: controller.signal.aborted ? "timeout" : "network_or_redirect" });
    } finally {
      clearTimeout(timer);
    }
  }

  function describeFailures(entries) {
    failures.replaceChildren();
    for (const [source, record] of entries) {
      const item = document.createElement("li");
      item.textContent = `${source.label}：${messages[record.error_code] || "接口暂不可用"}（${record.error_code}）`;
      failures.append(item);
    }
    failures.hidden = entries.length === 0;
  }

  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    login.hidden = true;
    failures.replaceChildren();
    failures.hidden = true;
    status.textContent = "正在读取研究上下文…仅查询现有记录，不调用模型。";
    try {
      const records = await Promise.all(sources.map(readSource));
      const failed = sources.flatMap((source, index) => records[index].status === "failed" ? [[source, records[index]]] : []);
      describeFailures(failed);
      const authenticationFailed = failed.some(([, record]) => ["login_required", "access_denied", "unexpected_html", "network_or_redirect"].includes(record.error_code));
      if (authenticationFailed) {
        status.textContent = "上下文未导出：部分来源的登录、权限或连接尚未确认。请完成飞书登录，确认访问权限后重新点击下载。";
        login.hidden = false;
        return;
      }
      const apiCount = sources.filter((source, index) => !["guide", "contract"].includes(source.name) && records[index].status === "ok").length;
      if (!apiCount) {
        status.textContent = "上下文未导出：没有取得可用的研究来源。请稍后重新点击下载。";
        return;
      }
      const generatedAt = new Date().toISOString();
      const snapshot = {
        schema_version: "1.0", generated_at: generatedAt, mode: "offline_snapshot",
        complete: failed.length === 0,
        readme: records[sources.findIndex((source) => source.name === "guide")].data ?? null,
        contract: records[sources.findIndex((source) => source.name === "contract")].data ?? null,
        failed_sources: failed.map(([source]) => source.name),
        sources: Object.fromEntries(sources.map((source, index) => [source.name, records[index]])),
      };
      const blob = new Blob([JSON.stringify(snapshot, null, 2) + "\n"], { type: "application/json;charset=utf-8" });
      const objectURL = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectURL;
      anchor.download = `research-context-${generatedAt.replace(/[:.]/g, "-")}.json`;
      anchor.hidden = true;
      status.textContent = failed.length
        ? `已下载不完整快照：11 个研究来源中取得 ${apiCount} 个；${failed.length} 个来源未取得，详见下方清单和文件内 failed_sources。它是离线记录，不代表实时状态。`
        : "研究上下文已下载：11 个研究来源及手册、接入约定。它是离线快照，请按每项来源的时间和范围使用。";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
    } catch {
      status.textContent = "上下文未导出：本次下载未完成。请稍后重新点击下载。";
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  });
})();
