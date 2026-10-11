export type Product = {
  product_id: string;
  name: string;
  brand: string;
  model: string;
  size_class: number;
  resolution_class: string;
  refresh_hz: number;
  review_count: number;
};
export type Condition = { type: string; condition: string; value: string };
export type Session = {
  previous_response_id: string;
  continuation: string;
  applied_filters: Record<string, unknown>;
  applied_conditions: Condition[];
};
export type Catalog = {
  products: Product[];
  metadata: {
    source_data_version: string;
    counts: { reviews: number; opinion_units: number };
  };
  api_ready: boolean;
};
export type ChatResult = Session & {
  answer: string;
  catalog_version: string;
  search_result?: {
    matched_count: number;
    products: Record<string, unknown>[];
  } | null;
};
export type ReportResult = {
  product: Product;
  markdown: string;
  units: { mapping_state: string }[];
  catalog_version: string;
};
const base = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);
export async function catalog(): Promise<Catalog> {
  const r = await fetch(base + "/catalog");
  if (!r.ok) throw new Error("카탈로그를 불러오지 못했습니다.");
  return r.json();
}
export async function stream<T>(
  path: string,
  body: unknown,
  signal: AbortSignal,
  onStatus: (s: string) => void,
): Promise<T> {
  const response = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok)
    throw new Error(
      response.status === 429
        ? "요청이 많습니다. 잠시 후 다시 시도해 주세요."
        : `요청을 처리하지 못했습니다 (${response.status}).`,
    );
  if (!response.body) throw new Error("응답 스트림을 열지 못했습니다.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    result: T | undefined;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const event = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const line = event.split("\n").find((v) => v.startsWith("data: "));
        if (!line) continue;
        const data = JSON.parse(line.slice(6));
        if (data.type === "error") throw new Error(data.message);
        if (data.type === "status") onStatus(data.message);
        if (data.type === "result") result = data.data as T;
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (result === undefined)
    throw new Error(
      "응답이 완료되기 전에 연결이 종료되었습니다. 다시 시도해 주세요.",
    );
  return result;
}
