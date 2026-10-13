// Pure helpers for the /api/explore/ai route: turn a headless CLI's failure
// into the `<<error:{...}>>` envelope the web stream parser understands, so a
// dead CLI surfaces as a real error instead of an empty "no matches" result.
// Plain .mjs so `node --test` can import it (same pattern as
// portals-serialize.mjs / stream-parse.mjs).

/**
 * Serialize one error envelope line for the AI-search stream parser.
 * @param {string} message
 * @param {string} [hint]
 * @returns {string}
 */
export function errorEnvelope(message, hint) {
  const payload = { message };
  if (hint) payload.hint = hint;
  return `<<error:${JSON.stringify(payload)}>>\n`;
}

const AUTH_RE = /authenticat|oauth|log ?in|not logged/i;
const RATE_LIMIT_RE = /rate limit|overloaded|429/i;

/**
 * The one-line follow-up action for a known failure family. "" when the
 * failure isn't one we can name.
 * @param {string} message
 * @returns {string}
 */
export function hintFor(message) {
  if (AUTH_RE.test(message)) return "Run `claude login` in a terminal, then retry.";
  if (RATE_LIMIT_RE.test(message)) return "The API is rate-limited — wait a minute and retry.";
  return "";
}

/**
 * Classify one parsed stream-json line from `claude -p --output-format
 * stream-json`. Returns null for lines that carry no failure, or
 * { message, hint } for:
 *  - synthetic assistant messages (model "<synthetic>" — the CLI's own
 *    failure notice, e.g. an expired OAuth session), whose text blocks ARE
 *    the message;
 *  - a result line with is_error === true (message from result/error, else
 *    a generic terminal_reason phrasing).
 * @param {Record<string, unknown>} obj
 * @returns {{message: string, hint: string} | null}
 */
export function classifyClaudeLine(obj) {
  if (!obj || typeof obj !== "object") return null;
  if (obj.type === "assistant" && obj.message?.model === "<synthetic>") {
    const blocks = Array.isArray(obj.message.content) ? obj.message.content : [];
    const message = blocks.map((b) => (b && typeof b.text === "string" ? b.text : "")).join("").trim();
    if (!message) return null;
    return { message, hint: hintFor(message) };
  }
  if (obj.type === "result" && obj.is_error === true) {
    const message = (typeof obj.result === "string" && obj.result) || (typeof obj.error === "string" && obj.error) || `Claude Code exited with ${obj.terminal_reason || "an error"}`;
    return { message, hint: hintFor(message) };
  }
  return null;
}

/**
 * Message+hint for a CLI that produced no output at all.
 * @param {string} cliName
 * @returns {{message: string, hint: string}}
 */
export function noOutputMessage(cliName) {
  return {
    message: `No output from ${cliName} — is it installed and signed in?`,
    hint: "Run it once in a terminal to sign in, then retry.",
  };
}
