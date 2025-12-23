type HomeAssistant = {
  callWS?: <T>(msg: Record<string, unknown>) => Promise<T>;
};

export type ConfigEntrySummary = {
  entry_id: string;
  title: string;
  unique_id?: string | null;
};

export type EntityRegistryEntry = {
  entity_id: string;
  config_entry_id?: string | null;
};

export function slugifyId(value: string): string {
  return value
    .normalize("NFKD")
    .replaceAll(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replaceAll(/[^a-z0-9]+/g, "_")
    .replaceAll(/^_+|_+$/g, "");
}

export function parseIdFromTitle(title: string): string | undefined {
  const match = /\((?<id>[^)]+)\)\s*$/.exec(title);
  return match?.groups?.id?.trim() || undefined;
}

export function resolveIdentifierFromEntry(
  entry: ConfigEntrySummary
): string | undefined {
  const uniqueId = typeof entry.unique_id === "string" ? entry.unique_id.trim() : "";
  if (uniqueId && uniqueId.toLowerCase() !== "none") {
    return uniqueId;
  }
  return parseIdFromTitle(entry.title) ?? entry.entry_id;
}

export async function fetchConfigEntries(
  hass: HomeAssistant | undefined,
  domain = "visitor_parking"
): Promise<ConfigEntrySummary[]> {
  if (!hass?.callWS) return [];
  return hass.callWS<ConfigEntrySummary[]>({
    type: "config_entries/get",
    domain,
  });
}

export async function fetchEntityRegistryEntries(
  hass: HomeAssistant | undefined
): Promise<EntityRegistryEntry[]> {
  if (!hass?.callWS) return [];
  return hass.callWS<EntityRegistryEntry[]>({
    type: "config/entity_registry/list",
  });
}

export async function resolveIdFromConfigEntry(
  hass: HomeAssistant | undefined,
  entryId: string
): Promise<string | undefined> {
  if (!hass?.callWS) return undefined;
  const entries = await fetchConfigEntries(hass, "visitor_parking");
  const entry = entries.find((e) => e.entry_id === entryId);
  if (!entry) return undefined;

  return resolveIdentifierFromEntry(entry);
}

export const parseMeldnummerFromTitle = parseIdFromTitle;
export const resolveMeldnummerFromConfigEntry = resolveIdFromConfigEntry;
