import en from "../translations/en.json";
import nl from "../translations/nl.json";

type Translations = Record<string, unknown>;

const TRANSLATIONS: Record<string, Translations> = { en, nl };

const DEFAULT_LANGUAGE = "en";

function _deepGet(obj: unknown, path: string): string | undefined {
  if (!obj || typeof obj !== "object") return undefined;
  let current: unknown = obj;
  for (const segment of path.split(".")) {
    if (!current || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return typeof current === "string" ? current : undefined;
}

function _format(
  template: string,
  placeholders: Record<string, string> | undefined
): string {
  if (!placeholders) return template;
  return template.replaceAll(/\{(?<key>[a-zA-Z0-9_]+)\}/g, (match, key) => {
    if (!key) return match;
    return Object.prototype.hasOwnProperty.call(placeholders, key)
      ? placeholders[key]
      : match;
  });
}

export function localize(
  hass: unknown,
  key: string,
  placeholders?: Record<string, string>
): string {
  const hassObj = hass as { locale?: { language?: string } } | undefined;
  return localizeLanguage(hassObj?.locale?.language, key, placeholders);
}

export function localizeLanguage(
  language: string | undefined,
  key: string,
  placeholders?: Record<string, string>
): string {
  const resolvedLanguage = language ?? DEFAULT_LANGUAGE;

  const table =
    TRANSLATIONS[resolvedLanguage] ??
    TRANSLATIONS[resolvedLanguage.split("-")[0]] ??
    TRANSLATIONS[DEFAULT_LANGUAGE];

  return _format(
    _deepGet(table, key) ??
      _deepGet(TRANSLATIONS[DEFAULT_LANGUAGE], key) ??
      key,
    placeholders
  );
}
