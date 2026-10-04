/**
 * Mock mode (`NEXT_PUBLIC_API_MOCK=1`): fixture responses shaped exactly like
 * the API's (spec §6), so the UI can be built and screenshotted without the backend.
 *
 * The answer fixture is an Expo SDK 58 question about local notifications with
 * five retrieved passages, three cited, and one invented citation ([7]) that the
 * verifier removes. The diff fixture is a real documented change: SDK 53
 * deprecated `shouldShowAlert` in the notification handler in favour of
 * `shouldShowBanner` and `shouldShowList`, and dropped push notifications from
 * Expo Go on Android. Passage snippets are short paraphrases of the Expo docs
 * (MIT); URLs point at the real pages.
 *
 * Magic questions on /ask (mock mode only):
 *   contains "rate limit"  -> 429 before the stream     "offline"  -> network error
 *   contains "fail"        -> { kind: "error" } mid-stream  "cut off" -> stream ends without done
 *   contains "weather"     -> no supporting passages, answer labelled unsupported
 * Stored questions: /q/demo-notifications (answer) and /q/demo-diff (What changed?).
 */
import { ApiError, networkError } from "./errors";
import type { AskEvent, AskInput } from "./api";
import { parseAskEvent } from "./api";

const EXPO = "https://docs.expo.dev";

export const EXAMPLE_QUESTION = "How do I schedule a local notification in SDK 58?";
export const EXAMPLE_VERSION = "v58.0.0";

/* ---------- versions ---------- */

export const versionsFixture = {
  sources: [
    {
      name: "expo",
      embedding_model: "voyage-4-lite (1024-d)",
      versions: [
        { version: "v58.0.0", chunk_count: 6184, ingested_at: "2026-10-03T18:20:00Z", commit_sha: "4f1c2ab" },
        { version: "v57.0.0", chunk_count: 6012, ingested_at: "2026-10-03T18:02:00Z", commit_sha: "4f1c2ab" },
        // Older versions are present in the mock only, so the diff fixture (a real SDK 52 -> 53 change) is truthful.
        { version: "v53.0.0", chunk_count: 5320, ingested_at: "2026-10-03T17:40:00Z", commit_sha: "4f1c2ab" },
        { version: "v52.0.0", chunk_count: 5188, ingested_at: "2026-10-03T17:31:00Z", commit_sha: "4f1c2ab" },
        { version: "unversioned", chunk_count: 2210, ingested_at: "2026-10-03T17:20:00Z", commit_sha: "4f1c2ab" },
      ],
    },
    {
      name: "react-native",
      embedding_model: "voyage-4-lite (1024-d)",
      versions: [{ version: "current", chunk_count: 1874, ingested_at: "2026-10-03T18:31:00Z", commit_sha: "9b0e7d1" }],
    },
  ],
};

/* ---------- answer fixture: SDK 58, local notifications ---------- */

const notif = (v: string, anchor: string) => `${EXPO}/versions/${v}/sdk/notifications/#${anchor}`;

export function answerChunks(version = EXAMPLE_VERSION) {
  const label = version;
  return [
    {
      id: "c_8f12a0",
      n: 1,
      title: "scheduleNotificationAsync(request)",
      heading_path: ["Notifications", "API", "Methods", "scheduleNotificationAsync(request)"],
      url: notif(version, "schedulenotificationasyncrequest"),
      version: label,
      score: 0.912,
      snippet:
        "Schedules a notification to be triggered in the future. The request takes the notification content and a trigger. Pass a time interval trigger with type SchedulableTriggerInputTypes.TIME_INTERVAL and a number of seconds, or null to present the notification immediately. Returns a promise that resolves to the notification identifier.",
    },
    {
      id: "c_8f12b7",
      n: 2,
      title: "setNotificationHandler(handler)",
      heading_path: ["Notifications", "API", "Methods", "setNotificationHandler(handler)"],
      url: notif(version, "setnotificationhandlerhandler"),
      version: label,
      score: 0.874,
      snippet:
        "When a notification is received while the app is running, the handler decides how it is presented. If no handler is set, the notification is not shown while the app is in the foreground. Return shouldShowBanner and shouldShowList to display it, and shouldPlaySound and shouldSetBadge as needed.",
    },
    {
      id: "c_8f13c4",
      n: 3,
      title: "Android notification channels",
      heading_path: ["Notifications", "Usage", "Android notification channels"],
      url: notif(version, "android-notification-channels"),
      version: label,
      score: 0.803,
      snippet:
        "On Android 8.0 (API level 26) and higher, every notification must be assigned to a channel. Create the channel with setNotificationChannelAsync before you schedule or receive notifications, otherwise they will not be displayed.",
    },
    {
      id: "c_8f1411",
      n: 4,
      title: "requestPermissionsAsync(permissions)",
      heading_path: ["Notifications", "API", "Methods", "requestPermissionsAsync(permissions)"],
      url: notif(version, "requestpermissionsasyncpermissions"),
      version: label,
      score: 0.741,
      snippet:
        "Prompts the user for notification permissions. On iOS you can request specific options such as alerts, badges and sounds. Returns the current permission status.",
    },
    {
      id: "g_1c09e2",
      n: 5,
      title: "Push notifications setup",
      heading_path: ["Guides", "Push notifications", "Setup"],
      url: `${EXPO}/push-notifications/push-notifications-setup/`,
      version: "unversioned",
      score: 0.688,
      snippet:
        "To receive push notifications you need a development build, the project ID from EAS, and an Expo push token for the device. Local notifications do not need a push token.",
    },
  ];
}

export const answerText = `To schedule a local notification, call \`Notifications.scheduleNotificationAsync\` with the notification \`content\` and a \`trigger\` [1]. Triggers are typed objects: for a delay, pass \`type: SchedulableTriggerInputTypes.TIME_INTERVAL\` with a number of \`seconds\` [1].

\`\`\`ts
import * as Notifications from "expo-notifications";

await Notifications.scheduleNotificationAsync({
  content: { title: "Time to stretch", body: "You asked to be reminded." },
  trigger: {
    type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
    seconds: 60,
  },
});
\`\`\`

Two things to set up once, before the first notification:

1. **A handler, if it should show while the app is open.** Without one, a notification that fires in the foreground is not shown. Call \`setNotificationHandler\` and return \`shouldShowBanner\` and \`shouldShowList\` [2].
2. **An Android channel.** On Android 8.0 and later, create a channel with \`setNotificationChannelAsync\` before scheduling, or the notification is not displayed [3][7].`;

export const answerCitations = {
  verified: [
    { n: 1, chunk_id: "c_8f12a0", url: notif(EXAMPLE_VERSION, "schedulenotificationasyncrequest"), quote: "Pass a time interval trigger with type SchedulableTriggerInputTypes.TIME_INTERVAL and a number of seconds" },
    { n: 2, chunk_id: "c_8f12b7", url: notif(EXAMPLE_VERSION, "setnotificationhandlerhandler"), quote: "If no handler is set, the notification is not shown while the app is in the foreground." },
    { n: 3, chunk_id: "c_8f13c4", url: notif(EXAMPLE_VERSION, "android-notification-channels"), quote: "Create the channel with setNotificationChannelAsync before you schedule or receive notifications" },
  ],
  removed: [{ n: 7, reason: "no passage [7] was retrieved; the marker was removed from the answer" }],
  unsupported: false,
};

/** Paid-rate cost: query embedding + one rerank + Groq gpt-oss-120b ($0.15 in / $0.60 out per 1M tokens). */
export const answerDone = {
  question_id: "demo-notifications",
  latency_ms: 2840,
  usage: { prompt_tokens: 4210, completion_tokens: 412, usd: 0.00091 },
};

/* ---------- diff fixture: SDK 52 -> SDK 53, notification handler ---------- */

export const DIFF_QUESTION = "How do I show notifications while the app is in the foreground?";
export const DIFF_OLD = "v52.0.0";
export const DIFF_NEW = "v53.0.0";

export const diffChunks = [
  {
    id: "c_52_a1",
    n: 1,
    title: "NotificationBehavior",
    heading_path: ["Notifications", "Types", "NotificationBehavior"],
    url: notif(DIFF_OLD, "notificationbehavior"),
    version: DIFF_OLD,
    score: 0.902,
    snippet:
      "An object returned by the notification handler that decides how a notification received in the foreground is presented: shouldShowAlert, shouldPlaySound, shouldSetBadge and an optional priority.",
  },
  {
    id: "c_52_b4",
    n: 2,
    title: "Notifications in Expo Go",
    heading_path: ["Notifications", "Overview"],
    url: notif(DIFF_OLD, "overview"),
    version: DIFF_OLD,
    score: 0.611,
    snippet: "You can try local and push notifications in Expo Go on Android and iOS while you develop.",
  },
  {
    id: "c_53_a1",
    n: 3,
    title: "NotificationBehavior",
    heading_path: ["Notifications", "Types", "NotificationBehavior"],
    url: notif(DIFF_NEW, "notificationbehavior"),
    version: DIFF_NEW,
    score: 0.915,
    snippet:
      "shouldShowAlert is deprecated. Use shouldShowBanner to show the notification as a banner and shouldShowList to show it in the notification list. shouldPlaySound and shouldSetBadge are unchanged.",
  },
  {
    id: "c_53_b2",
    n: 4,
    title: "Notifications in Expo Go",
    heading_path: ["Notifications", "Overview"],
    url: notif(DIFF_NEW, "overview"),
    version: DIFF_NEW,
    score: 0.64,
    snippet:
      "Push notifications are not supported in Expo Go on Android. Use a development build to test them. Local notifications still work in Expo Go.",
  },
];

export const diffFixture = {
  summary:
    "SDK 53 splits the handler's single display flag in two: shouldShowAlert is deprecated in favour of shouldShowBanner and shouldShowList. It also drops push notifications from Expo Go on Android.",
  changes: [
    { kind: "renamed", before: "shouldShowAlert: true", after: "shouldShowBanner: true, shouldShowList: true", citations: [1, 3] },
    { kind: "added", before: null, after: "shouldShowList: keep it in the notification list without a banner", citations: [3] },
    {
      kind: "behaviour",
      before: "Push notifications testable in Expo Go on Android",
      after: "Android push needs a development build; local notifications still work in Expo Go",
      citations: [2, 4],
    },
  ],
};

export const diffText = `In SDK 52 the notification handler returns \`shouldShowAlert\` to show a notification that arrives while the app is open [1]. In SDK 53 that flag is deprecated: return \`shouldShowBanner\` for the banner and \`shouldShowList\` to keep it in the notification list [3].

\`\`\`ts
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});
\`\`\`

If you test on Android in Expo Go, note that push notifications stopped working there in SDK 53; local notifications are unaffected [2][4].`;

export const diffCitations = {
  verified: [
    { n: 1, chunk_id: "c_52_a1", url: diffChunks[0].url, quote: "shouldShowAlert, shouldPlaySound, shouldSetBadge" },
    { n: 2, chunk_id: "c_52_b4", url: diffChunks[1].url, quote: "local and push notifications in Expo Go on Android and iOS" },
    { n: 3, chunk_id: "c_53_a1", url: diffChunks[2].url, quote: "shouldShowAlert is deprecated." },
    { n: 4, chunk_id: "c_53_b2", url: diffChunks[3].url, quote: "Push notifications are not supported in Expo Go on Android." },
  ],
  removed: [],
  unsupported: false,
};

export const diffDone = {
  question_id: "demo-diff",
  latency_ms: 4120,
  usage: { prompt_tokens: 7390, completion_tokens: 655, usd: 0.00153 },
};

/* ---------- stored questions (GET /api/questions/{id}) ---------- */

export const storedQuestions: Record<string, unknown> = {
  "demo-notifications": {
    id: "demo-notifications",
    created_at: "2026-10-04T09:12:03Z",
    question: EXAMPLE_QUESTION,
    sdk: "expo",
    version: EXAMPLE_VERSION,
    mode: "answer",
    answer: answerText,
    chunks: answerChunks(),
    citations: answerCitations,
    usage: answerDone.usage,
    latency_ms: answerDone.latency_ms,
    feedback: null,
  },
  "demo-diff": {
    id: "demo-diff",
    created_at: "2026-10-04T09:20:41Z",
    question: DIFF_QUESTION,
    sdk: "expo",
    version: DIFF_NEW,
    compare_version: DIFF_OLD,
    mode: "diff",
    answer: diffText,
    chunks: diffChunks,
    citations: diffCitations,
    diff: diffFixture,
    usage: diffDone.usage,
    latency_ms: diffDone.latency_ms,
    feedback: "up",
  },
};

export function mockGetQuestion(qid: string): unknown {
  const q = storedQuestions[qid];
  if (!q) throw new ApiError({ status: 404, code: "question_not_found", message: `No stored question with id ${qid}.` });
  return q;
}

export async function mockVersions(): Promise<unknown> {
  await sleep(250);
  return versionsFixture;
}

export async function mockFeedback(qid: string, feedback: "up" | "down"): Promise<void> {
  await sleep(300);
  void qid;
  void feedback;
}

export function mockHealth() {
  return {
    status: "ok",
    db: "mock",
    providers: { embeddings: "voyage (mock)", llm: "groq (mock)", rerank: "voyage (mock)" },
    corpora: versionsFixture.sources.map((s) => ({ name: s.name, versions: s.versions.length })),
  };
}

/* ---------- streaming ---------- */

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });
}

/** Split text into small deltas the way a model streams: a few characters to a word at a time. */
export function tokenise(text: string): string[] {
  return text.match(/\s*\S{1,6}|\s+/g) ?? [];
}

function scriptFor(body: AskInput): { payloads: Record<string, unknown>[]; failAt?: number; cutAt?: number } {
  const q = body.question.toLowerCase();
  const isDiff = body.mode === "diff";

  if (q.includes("weather")) {
    return {
      payloads: [
        { kind: "retrieval", chunks: [] },
        ...tokenise(
          "The retrieved documentation does not cover this. DocPilot only answers from the Expo and React Native docs; try a question about an API, a config key or a guide.",
        ).map((t) => ({ kind: "token", text: t })),
        { kind: "citations", verified: [], removed: [], unsupported: true },
        { kind: "done", question_id: null, latency_ms: 910, usage: { prompt_tokens: 380, completion_tokens: 41, usd: 0.00008 } },
      ],
    };
  }

  if (isDiff) {
    const pair = new Set([body.version, body.compare_version]);
    const known = pair.has(DIFF_OLD) && pair.has(DIFF_NEW);
    if (!known) {
      return {
        payloads: [
          { kind: "retrieval", chunks: answerChunks(body.version).slice(0, 2) },
          ...tokenise(
            "The mock corpus only has a documented difference for SDK 52 and SDK 53. Pick those two versions to see the What changed? view with a structured diff.",
          ).map((t) => ({ kind: "token", text: t })),
          { kind: "citations", verified: [], removed: [], unsupported: true },
          { kind: "diff", diff: { summary: "No difference found in the passages for these two versions.", changes: [] } },
          { kind: "done", question_id: null, latency_ms: 1850, usage: { prompt_tokens: 2100, completion_tokens: 60, usd: 0.00035 } },
        ],
      };
    }
    return {
      payloads: [
        { kind: "retrieval", chunks: diffChunks },
        { kind: "diff", diff: diffFixture },
        ...tokenise(diffText).map((t) => ({ kind: "token", text: t })),
        { kind: "citations", ...diffCitations },
        { kind: "done", ...diffDone },
      ],
    };
  }

  const payloads: Record<string, unknown>[] = [
    { kind: "retrieval", chunks: answerChunks(body.version) },
    ...tokenise(answerText).map((t) => ({ kind: "token", text: t })),
    { kind: "citations", ...answerCitations },
    { kind: "done", ...answerDone },
  ];
  if (q.includes("fail")) return { payloads, failAt: 40 };
  if (q.includes("cut off")) return { payloads, cutAt: 60 };
  return { payloads };
}

/** Plays a fixture as an SSE stream would: each payload goes through the real event parser. */
export async function mockAsk(
  body: AskInput,
  onEvent: (e: AskEvent) => void,
  signal?: AbortSignal,
): Promise<{ terminal: boolean }> {
  const q = body.question.toLowerCase();
  await sleep(200, signal);
  if (q.includes("rate limit")) {
    throw new ApiError({
      status: 429,
      code: "rate_limited",
      message: "Too many questions from this address. The limit is 30 questions per hour.",
      retryAfter: 1260,
    });
  }
  if (q.includes("offline")) throw networkError("http://localhost:7860");

  const { payloads, failAt, cutAt } = scriptFor(body);
  for (let i = 0; i < payloads.length; i++) {
    if (signal?.aborted) return { terminal: false };
    if (failAt !== undefined && i === failAt) {
      onEvent({ kind: "error", code: "unavailable", message: "The model provider timed out. Try again in a minute." });
      return { terminal: true };
    }
    if (cutAt !== undefined && i === cutAt) return { terminal: false };
    const p = payloads[i];
    await sleep(p.kind === "retrieval" ? 650 : p.kind === "token" ? 18 : p.kind === "diff" ? 300 : 220, signal);
    if (signal?.aborted) return { terminal: false };
    const ev = parseAskEvent(JSON.stringify(p));
    if (ev) onEvent(ev);
  }
  return { terminal: true };
}
