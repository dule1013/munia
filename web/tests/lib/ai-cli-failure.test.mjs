// The /api/explore/ai route turns a headless CLI failure into a <<error:…>>
// envelope instead of the old plain-text "(no output — is the CLI
// authenticated?)" — the parser then surfaces it as a real error, not an
// empty "no matches" result. Covers the two real stream-json lines a dead
// Claude CLI emits (expired OAuth: synthetic assistant message + is_error
// result) plus the envelope round-trip through the real parser.
//
// Run:  node --test tests/lib/ai-cli-failure.test.mjs
// (the parser import is .ts — under a Node that can't strip types run:
//  node --experimental-strip-types --test tests/lib/ai-cli-failure.test.mjs)

import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyClaudeLine, errorEnvelope, hintFor, noOutputMessage } from "../../src/lib/ai-cli-failure.mjs";
import { makeAiStreamParser } from "../../src/lib/explore-ai.ts";

const AUTH_MESSAGE = "Failed to authenticate: OAuth session expired and could not be refreshed";

test("synthetic assistant message → its text, with the claude login hint", () => {
  const line = { type: "assistant", message: { model: "<synthetic>", content: [{ type: "text", text: AUTH_MESSAGE }] } };
  const out = classifyClaudeLine(line);
  assert.equal(out.message, AUTH_MESSAGE);
  assert.equal(out.hint, "Run `claude login` in a terminal, then retry.");
});

test("result is_error without text → generic terminal_reason message", () => {
  const out = classifyClaudeLine({ type: "result", is_error: true, terminal_reason: "api_error", subtype: "success" });
  assert.equal(out.message, "Claude Code exited with api_error");
  assert.equal(out.hint, "");
});

test("result is_error carrying text → that text wins", () => {
  const out = classifyClaudeLine({ type: "result", is_error: true, result: "boom" });
  assert.equal(out.message, "boom");
});

test("non-failure lines classify to null", () => {
  assert.equal(classifyClaudeLine({ type: "assistant", message: { model: "claude-haiku-4-5", content: [{ type: "text", text: "hi" }] } }), null);
  assert.equal(classifyClaudeLine({ type: "result", is_error: false }), null);
  assert.equal(classifyClaudeLine({ type: "stream_event" }), null);
});

test("hintFor: auth / rate-limit / unknown families", () => {
  assert.match(hintFor(AUTH_MESSAGE), /claude login/);
  assert.match(hintFor("Error: not logged in"), /claude login/);
  assert.match(hintFor("429 rate limit hit"), /rate-limited/);
  assert.match(hintFor("API overloaded, try later"), /rate-limited/);
  assert.equal(hintFor("something else broke"), "");
});

test("noOutputMessage names the CLI and carries the sign-in hint", () => {
  const { message, hint } = noOutputMessage("Gemini");
  assert.equal(message, "No output from Gemini — is it installed and signed in?");
  assert.ok(hint);
});

test("errorEnvelope round-trips through the real stream parser", () => {
  const parser = makeAiStreamParser();
  const chunks = parser.feed(errorEnvelope(AUTH_MESSAGE, "Run `claude login` in a terminal, then retry."));
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].kind, "error");
  assert.equal(chunks[0].message, AUTH_MESSAGE);
  assert.match(chunks[0].hint, /claude login/);
});

test("an <<error:…>> envelope split across two chunks yields exactly one error chunk", () => {
  const parser = makeAiStreamParser();
  const line = errorEnvelope("CLI died", "try again");
  const cut = line.indexOf("{") + 3; // mid-JSON, past the <<error: opener
  const chunks = [...parser.feed(line.slice(0, cut)), ...parser.feed(line.slice(cut))];
  const errors = chunks.filter((c) => c.kind === "error");
  assert.equal(errors.length, 1);
  assert.equal(errors[0].message, "CLI died");
  assert.equal(errors[0].hint, "try again");
});
