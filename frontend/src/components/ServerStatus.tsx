import { useState } from "react";
import { USE_MOCKS, checkServerHealth } from "../api";

type CheckState =
  | { status: "idle" }
  | { status: "checking" }
  | { status: "ok"; latencyMs: number; payload: unknown }
  | { status: "error"; message: string };

export function ServerStatus() {
  const [state, setState] = useState<CheckState>({ status: "idle" });

  const runCheck = async () => {
    setState({ status: "checking" });
    const startedAt = performance.now();

    try {
      const payload = await checkServerHealth();
      setState({
        status: "ok",
        latencyMs: Math.round(performance.now() - startedAt),
        payload,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setState({ status: "error", message });
    }
  };

  return (
    <article className="card">
      <h3>Тестовый режим: проверка сервера</h3>
      <p>
        Текущий источник данных: <b>{USE_MOCKS ? "Mock mode" : "Backend API"}</b>
      </p>
      <button type="button" onClick={runCheck} disabled={state.status === "checking"}>
        {state.status === "checking" ? "Проверяем..." : "Проверить сервер (/health)"}
      </button>

      {state.status === "ok" ? (
        <p className="status-ok">✅ Сервер доступен, latency: {state.latencyMs} ms.</p>
      ) : null}

      {state.status === "error" ? (
        <p className="status-error">❌ Сервер недоступен: {state.message}</p>
      ) : null}

      {state.status === "ok" ? (
        <pre className="status-payload">{JSON.stringify(state.payload, null, 2)}</pre>
      ) : null}
    </article>
  );
}
