import { LitElement, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { localize, localizeLanguage } from "./localize";
import {
  ConfigEntrySummary,
  EntityRegistryEntry,
  fetchConfigEntries,
  fetchEntityRegistryEntries,
} from "./config-entry";
import "./visitor-parking-active-reservation-card-editor";

type HassEntity = {
  attributes?: Record<string, unknown>;
};

type HomeAssistant = {
  states: Record<string, HassEntity | undefined>;
  callService: (
    domain: string,
    service: string,
    data?: Record<string, unknown>
  ) => Promise<unknown>;
  callWS?: <T>(msg: Record<string, unknown>) => Promise<T>;
  user?: { is_admin: boolean };
};

type VisitorParkingReservation = {
  id?: number | string;
  name?: string;
  license_plate?: string;
  start_time?: string;
  end_time?: string;
};

type ReservationWithEntry = VisitorParkingReservation & {
  entryId?: string;
  entryTitle?: string;
};

type VisitorParkingCardConfig = {
  type: string;
  entity?: string;
  title?: string;
  config_entry_id?: string;
};

@customElement("visitor-parking-card")
export class VisitorParkingCard extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @state() private _config?: VisitorParkingCardConfig;
  @state() private _endingReservationIds = new Set<string>();
  @state() private _entries: ConfigEntrySummary[] = [];
  @state() private _entriesLoaded = false;
  @state() private _entityRegistry: EntityRegistryEntry[] = [];
  @state() private _entityRegistryLoaded = false;

  public setConfig(config: VisitorParkingCardConfig): void {
    this._config = config;
  }

  protected updated(_changedProps: Map<string, unknown>) {
    if (!this.hass || !this._config) return;

    if (!this._entriesLoaded) {
      if (!this.hass.user?.is_admin || !this.hass.callWS) {
        this._entriesLoaded = true;
      } else {
        void this._loadEntries();
      }
    }
    if (!this._entityRegistryLoaded) {
      if (!this.hass.user?.is_admin || !this.hass.callWS) {
        this._entityRegistryLoaded = true;
      } else {
        void this._loadEntityRegistry();
      }
    }

    if (this._config.entity) return;
  }

  public static getConfigElement(): HTMLElement {
    return document.createElement(
      "visitor-parking-active-reservation-card-editor"
    );
  }

  public static getStubConfig(): VisitorParkingCardConfig {
    return {
      type: "custom:visitor-parking-card",
    };
  }

  public getCardSize(): number {
    return (this._reservations?.length ?? 0) + 1;
  }

  // Sections view support (recent HA)
  public getGridOptions() {
    return {
      columns: "full" as const,
      rows: Math.max(2, (this._reservations?.length ?? 0) + 1),
    };
  }

  private async _loadEntries(): Promise<void> {
    if (!this.hass) return;
    try {
      const entries = await fetchConfigEntries(this.hass, "visitor_parking");
      this._entries = entries;
    } catch (_err) {
      this._entries = [];
    } finally {
      this._entriesLoaded = true;
    }
  }

  private async _loadEntityRegistry(): Promise<void> {
    if (!this.hass) return;
    try {
      this._entityRegistry = await fetchEntityRegistryEntries(this.hass);
    } catch (_err) {
      this._entityRegistry = [];
    } finally {
      this._entityRegistryLoaded = true;
    }
  }

  private get _reservationsEntityId(): string | undefined {
    if (!this._config) return undefined;
    const override = (this._config.entity ?? "").trim();
    return override || undefined;
  }

  private get _entity(): HassEntity | undefined {
    const entityId = this._reservationsEntityId;
    return this.hass && entityId ? this.hass.states[entityId] : undefined;
  }

  private _entryTitleMap(): Map<string, string> {
    const map = new Map<string, string>();
    for (const entry of this._entries) {
      map.set(entry.entry_id, entry.title);
    }
    return map;
  }

  private _entryFromEntityId(entityId: string): { entryId?: string; title?: string } {
    const registryEntry = this._entityRegistry.find(
      (item) => item.entity_id === entityId
    );
    const entryId = registryEntry?.config_entry_id ?? undefined;
    if (!entryId) return {};
    const mappedTitle = this._entryTitleMap().get(entryId);
    return { entryId, title: mappedTitle };
  }

  private get _reservations(): ReservationWithEntry[] | undefined {
    if (this._reservationsEntityId) {
      const reservations = this._entity?.attributes?.reservations;
      return Array.isArray(reservations)
        ? (reservations as ReservationWithEntry[])
        : undefined;
    }

    if (!this.hass) return undefined;
    const fallbackEntryId =
      this._entriesLoaded && this._entries.length === 1
        ? this._entries[0].entry_id
        : undefined;
    const fallbackTitle =
      this._entriesLoaded && this._entries.length === 1
        ? this._entries[0].title
        : undefined;

    const results: ReservationWithEntry[] = [];
    for (const [entityId, state] of Object.entries(this.hass.states)) {
      if (
        !entityId.startsWith("sensor.visitor_parking_") ||
        !entityId.endsWith("_reservations") ||
        !state
      ) {
        continue;
      }
      const reservations = state.attributes?.reservations;
      if (!Array.isArray(reservations)) continue;
      const entryInfo = this._entryFromEntityId(entityId);
      const entryId = entryInfo.entryId ?? fallbackEntryId;
      const entryTitle = entryInfo.title ?? fallbackTitle;
      for (const reservation of reservations) {
        if (!reservation || typeof reservation !== "object") continue;
        results.push({
          ...(reservation as VisitorParkingReservation),
          entryId,
          entryTitle,
        });
      }
    }
    return results;
  }

  private _notify(message: string): void {
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: { message },
        bubbles: true,
        composed: true,
      })
    );
  }

  private _reservationLabel(reservation: VisitorParkingReservation): string {
    const name = (reservation.name ?? "").trim();
    const plate = (reservation.license_plate ?? "").trim();
    return (
      (name && plate ? `${name} - ${plate}` : name || plate) ||
      localize(this.hass, "active_reservation_card.reservation_fallback_label")
    );
  }

  private _formatTime(value?: string): string | undefined {
    if (!value) return;
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? undefined
      : date.toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
        });
  }

  private _formatTimeRange(
    reservation: VisitorParkingReservation
  ): string | undefined {
    const start = this._formatTime(reservation.start_time);
    const end = this._formatTime(reservation.end_time);
    return start && end ? `${start}–${end}` : start || end;
  }

  private _reservationId(value: VisitorParkingReservation["id"]): string | null {
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed ? trimmed : null;
    }
    return null;
  }

  private async _endReservation(
    reservationId: string,
    entryId?: string
  ): Promise<void> {
    if (!this.hass || !this._config) return;
    if (!entryId && this._entriesLoaded && this._entries.length > 1) return;

    this._endingReservationIds = new Set(this._endingReservationIds).add(
      reservationId
    );

    try {
      await this.hass.callService("visitor_parking", "delete_reservation", {
        reservation_id: reservationId,
        ...(entryId && {
          config_entry_id: entryId,
        }),
      });
    } finally {
      const next = new Set(this._endingReservationIds);
      next.delete(reservationId);
      this._endingReservationIds = next;
    }
  }

  protected render() {
    if (!this.hass || !this._config) return nothing;

    const title =
      this._config.title ??
      localize(this.hass, "active_reservation_card.default_title");
    if (this._reservationsEntityId) {
      if (!this._entity) {
        return html`
          <ha-card>
            <div class="card-content">
              ${localize(this.hass, "active_reservation_card.entity_not_found", {
                entity: this._reservationsEntityId ?? "",
              })}
            </div>
          </ha-card>
        `;
      }

      const reservations = this._reservations ?? [];
      return html`
        <ha-card header=${title}>
          <div class="card-content">
            ${reservations.length === 0
              ? html`<div class="empty">
                  ${localize(
                    this.hass,
                    "active_reservation_card.no_active_reservations"
                  )}
                </div>`
              : html`
                  <div class="list">
                    ${reservations.map((r) => {
                      const id = this._reservationId(r.id);
                      const canEnd = Boolean(id);
                      const ending = Boolean(
                        id && this._endingReservationIds.has(id)
                      );
                      const time = this._formatTimeRange(r);

                      return html`
                        <div class="row">
                          <div class="main">
                            <div class="label">${this._reservationLabel(r)}</div>
                            ${time ? html`<div class="time">${time}</div>` : nothing}
                          </div>
                          <div class="actions">
                            <ha-button
                              appearance="outlined"
                              .disabled=${!canEnd || ending}
                              @click=${() => id && this._endReservation(id)}
                            >
                              ${ending
                                ? localize(this.hass, "common.working")
                                : localize(
                                    this.hass,
                                    "active_reservation_card.end"
                                  )}
                            </ha-button>
                          </div>
                        </div>
                      `;
                    })}
                  </div>
                `}
          </div>
        </ha-card>
      `;
    }

    const reservations = this._reservations ?? [];
    const showEntryLabel = this._entriesLoaded && this._entries.length > 1;
    const allowEndWithoutEntry = this._entriesLoaded && this._entries.length <= 1;

    return html`
      <ha-card header=${title}>
        <div class="card-content">
          ${reservations.length === 0
            ? html`<div class="empty">
                ${localize(this.hass, "active_reservation_card.no_active_reservations")}
              </div>`
            : html`
                <div class="list">
                  ${reservations.map((r) => {
                    const id = this._reservationId(r.id);
                    const canEnd =
                      Boolean(id) &&
                      (allowEndWithoutEntry || Boolean(r.entryId));
                    const ending = Boolean(id && this._endingReservationIds.has(id));
                    const time = this._formatTimeRange(r);

                    return html`
                      <div class="row">
                        <div class="main">
                          <div class="label">${this._reservationLabel(r)}</div>
                          ${showEntryLabel && r.entryTitle
                            ? html`<div class="entry">${r.entryTitle}</div>`
                            : nothing}
                          ${time ? html`<div class="time">${time}</div>` : nothing}
                        </div>
                        <div class="actions">
                          <ha-button
                            appearance="outlined"
                            .disabled=${!canEnd || ending}
                            @click=${() => id && this._endReservation(id, r.entryId)}
                          >
                            ${ending
                              ? localize(this.hass, "common.working")
                              : localize(this.hass, "active_reservation_card.end")}
                          </ha-button>
                        </div>
                      </div>
                    `;
                  })}
                </div>
              `}
        </div>
      </ha-card>
    `;
  }

  static styles = css`
    .card-content {
      padding: 16px;
    }

    .empty {
      color: var(--secondary-text-color);
    }

    .list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .main {
      min-width: 0;
    }

    .actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }

    .label {
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .entry {
      margin-top: 2px;
      color: var(--secondary-text-color);
      font-size: 0.85em;
    }

    .time {
      margin-top: 2px;
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
  `;
}

(window as any).customCards ??= [];
(window as any).customCards.push({
  type: "visitor-parking-card",
  name: localizeLanguage(
    globalThis.navigator?.language,
    "active_reservation_card.card_name"
  ),
  description: localizeLanguage(
    globalThis.navigator?.language,
    "active_reservation_card.card_description"
  ),
  editor: "visitor-parking-active-reservation-card-editor",
});

declare global {
  interface HTMLElementTagNameMap {
    "visitor-parking-card": VisitorParkingCard;
  }
}
