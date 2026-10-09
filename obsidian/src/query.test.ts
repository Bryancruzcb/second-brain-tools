import { describe, expect, test } from "bun:test";

import { askVault, buildRequest, QueryError, queryUrl, toCallout, type Transport } from "./query";

const OK = {
  answer: "According to your notes on Levain, feed it 1:1:1.",
  sources: [{ title: "Levain", source: "Baking/Levain.md", snippet: "...", distance: 0.12 }],
  api_configured: true,
};

function fake(status: number, body: unknown, calls: Parameters<Transport>[0][] = []): Transport {
  return async (req) => {
    calls.push(req);
    return { status, text: typeof body === "string" ? body : JSON.stringify(body) };
  };
}

describe("request", () => {
  test("posts the existing QueryRequest shape to /api/query", async () => {
    const calls: Parameters<Transport>[0][] = [];
    const res = await askVault(fake(200, OK, calls), "http://127.0.0.1:8000/", buildRequest("  feed levain?  ", "all"));

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://127.0.0.1:8000/api/query");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].contentType).toBe("application/json");
    expect(JSON.parse(calls[0].body)).toEqual({ query: "feed levain?", scope: "all" });
    expect(res).toEqual(OK);
  });

  test("context notes travel as context_nodes", () => {
    expect(buildRequest("q", "notes", ["A.md"])).toEqual({ query: "q", scope: "notes", context_nodes: ["A.md"] });
    expect(buildRequest("q", "notes", [])).toEqual({ query: "q", scope: "notes" });
  });

  test("queryUrl trims whitespace and trailing slashes", () => {
    expect(queryUrl(" http://host:8000// ")).toBe("http://host:8000/api/query");
  });
});

describe("errors", () => {
  test("blank question never reaches the transport", async () => {
    const calls: Parameters<Transport>[0][] = [];
    await expect(askVault(fake(200, OK, calls), "http://x", buildRequest("  ", "notes"))).rejects.toThrow(
      "Type a question first.",
    );
    expect(calls).toHaveLength(0);
  });

  test("FastAPI detail is surfaced with the status", async () => {
    const err = await askVault(fake(500, { detail: "model 'qwen3' not found" }), "http://x", buildRequest("q", "notes")).catch(
      (e) => e,
    );
    expect(err).toBeInstanceOf(QueryError);
    expect(err.status).toBe(500);
    expect(err.message).toBe("Backend error 500: model 'qwen3' not found");
  });

  test("non-JSON error body still reports the status", async () => {
    await expect(askVault(fake(502, "Bad Gateway"), "http://x", buildRequest("q", "notes"))).rejects.toThrow(
      "Backend error 502",
    );
  });

  test("transport failure reads as unreachable", async () => {
    const down: Transport = async () => {
      throw new Error("ECONNREFUSED");
    };
    await expect(askVault(down, "http://127.0.0.1:8000", buildRequest("q", "notes"))).rejects.toThrow(
      "unreachable at http://127.0.0.1:8000/api/query",
    );
  });

  test("200 without an answer is rejected", async () => {
    await expect(askVault(fake(200, { sources: [] }), "http://x", buildRequest("q", "notes"))).rejects.toThrow(
      "unexpected response",
    );
  });
});

describe("toCallout", () => {
  test("quotes every line and links sources by path", () => {
    const out = toCallout("feed\n levain?", { ...OK, answer: "Line one.\n\nLine two." });
    expect(out).toBe(
      [
        "> [!question] feed levain?",
        "> Line one.",
        ">",
        "> Line two.",
        ">",
        "> Sources:",
        "> - [[Baking/Levain]]",
        "",
      ].join("\n"),
    );
  });

  test("omits the sources block when there are none", () => {
    expect(toCallout("q", { ...OK, sources: [] })).toBe("> [!question] q\n> " + OK.answer + "\n");
  });
});
