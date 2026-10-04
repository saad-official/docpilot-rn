import type { Mode, Sdk } from "./api";

/** Example questions under the ask box. Each is a real question developers ask about that source. */
export type ExampleQuestion = {
  question: string;
  sdk: Sdk;
  mode: Mode;
  /** Preferred version pair for "What changed?", applied only when both versions are indexed. */
  prefer?: { version: string; compare: string };
};

export const EXAMPLES: ExampleQuestion[] = [
  { sdk: "expo", mode: "answer", question: "How do I schedule a local notification?" },
  { sdk: "expo", mode: "answer", question: "How do I read environment variables in app.config.ts?" },
  { sdk: "expo", mode: "answer", question: "How do I protect a route with Expo Router?" },
  {
    sdk: "expo",
    mode: "diff",
    question: "How do I show notifications while the app is in the foreground?",
    prefer: { version: "v53.0.0", compare: "v52.0.0" },
  },
  { sdk: "react-native", mode: "answer", question: "How do I make a FlatList render faster?" },
  { sdk: "react-native", mode: "answer", question: "When should I use useWindowDimensions instead of Dimensions?" },
];

export function examplesFor(sdk: Sdk, mode: Mode): ExampleQuestion[] {
  const same = EXAMPLES.filter((e) => e.sdk === sdk && e.mode === mode);
  const rest = EXAMPLES.filter((e) => e.sdk === sdk && e.mode !== mode);
  return [...same, ...rest].slice(0, 4);
}
