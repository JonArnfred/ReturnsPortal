/** Display names per broker key (`broker_connections.broker`). A new connector adds its key here. */
export const BROKERS = {
  saxo: { name: "SaxoBank", short: "Saxo", product: "SaxoBank OpenAPI" },
  ibkr: { name: "Interactive Brokers", short: "IBKR", product: "Interactive Brokers Flex" },
} as const;

export type Broker = keyof typeof BROKERS;

/** The broker's display name in the given form, or the raw key for a broker this list does not know. */
export function brokerLabel(key: string | null | undefined, form: keyof (typeof BROKERS)[Broker] = "name"): string {
  if (!key) return "";
  return key in BROKERS ? BROKERS[key as Broker][form] : key;
}
