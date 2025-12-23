import { LitElement, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { parseIdFromTitle, slugifyId } from "./config-entry";
import { localize } from "./localize";

type HomeAssistant = {
  states: Record<string, unknown>;
  callWS: <T>(msg: Record<string, unknown>) => Promise<T>;
  user?: { is_admin: boolean };
};

type VisitorParkingNewReservationCardConfig = {
  type: string;
  title?: string;
  config_entry_id?: string;
  favorites_entity?: string;
};

type ConfigEntryFragment = {
  entry_id: string;
  domain: string;
  title: string;
  unique_id?: string | null;
};

@customElement("visitor-parking-new-reservation-card-editor")
export class VisitorParkingNewReservationCardEditor extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @property({ attribute: false })
  private _config?: VisitorParkingNewReservationCardConfig;

  @state() private _entries: ConfigEntryFragment[] = [];
  @state() private _entriesLoaded = false;

  setConfig(config: VisitorParkingNewReservationCardConfig) {
    this._config = { ...config };
    this._selectDefaultEntryIfNeeded();
  }

  protected updated(changedProps: Map<string, unknown>) {
    if (!this.hass || this._entriesLoaded) return;
    if (changedProps.has("hass")) {
      if (!this.hass.user?.is_admin) {
        this._entriesLoaded = true;
        return;
      }
      void this._loadEntries();
    }
  }

  private async _loadEntries(): Promise<void> {
    if (!this.hass) return;
    try {
      const entries = await this.hass.callWS<ConfigEntryFragment[]>({
        type: "config_entries/get",
        domain: "visitor_parking",
      });
      this._entries = entries;
    } catch (_err) {
      this._entries = [];
    } finally {
      this._entriesLoaded = true;
      this._selectDefaultEntryIfNeeded();
    }
  }

  private _selectDefaultEntryIfNeeded(): void {
    if (!this._config) return;
    if (!this._entriesLoaded || this._entries.length === 0) return;

    if (this._config.config_entry_id) {
      if (!this._config.favorites_entity) {
        this._applyEntry(this._config.config_entry_id);
      }
      return;
    }

    if (this._entries.length !== 1) return;
    this._applyEntry(this._entries[0].entry_id);
  }

  private _applyEntry(entryId: string | undefined): void {
    if (!this._config) return;

    const entry = entryId
      ? this._entries.find((e) => e.entry_id === entryId)
      : undefined;

    let identifier: string | undefined;
    if (entry) {
      const uniqueId =
        typeof entry.unique_id === "string" ? entry.unique_id.trim() : "";
      identifier =
        uniqueId && uniqueId.toLowerCase() !== "none"
          ? uniqueId
          : parseIdFromTitle(entry.title);
    }

    const slug = identifier ? slugifyId(identifier) : undefined;
    const preferredFavorites = slug
      ? `sensor.visitor_parking_${slug}_favorites`
      : undefined;

    this._config = {
      ...this._config,
      config_entry_id: entryId,
      favorites_entity: preferredFavorites,
    };
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      })
    );
  }

  private _entryChanged(ev: Event) {
    this._applyEntry((ev.target as HTMLSelectElement).value || undefined);
  }

  render() {
    if (!this.hass) return nothing;

    return html`
      <div class="container">
        <div class="field">
          <div class="label">${localize(this.hass, "new_reservation_card.service")}</div>
          <select
            class="select"
            .value=${this._config?.config_entry_id ?? ""}
            @change=${this._entryChanged}
          >
            <option value="">
              ${localize(this.hass, "new_reservation_card.service_placeholder")}
            </option>
            ${this._entries.map(
              (entry) =>
                html`<option .value=${entry.entry_id}>${entry.title}</option>`
            )}
          </select>
        </div>
      </div>
    `;
  }

  static styles = css`
    .container {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .label {
      font-weight: 500;
    }

    .select {
      border: 1px solid var(--divider-color);
      border-radius: var(--ha-card-border-radius, 12px);
      background: transparent;
      color: var(--primary-text-color);
      padding: 10px 12px;
      min-height: 40px;
    }
  `;
}
