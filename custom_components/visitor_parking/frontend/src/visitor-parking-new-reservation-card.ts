import { LitElement, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { localize, localizeLanguage } from "./localize";
import {
  ConfigEntrySummary,
  EntityRegistryEntry,
  fetchConfigEntries,
  fetchEntityRegistryEntries,
  resolveIdFromConfigEntry,
  resolveIdentifierFromEntry,
  slugifyId,
} from "./config-entry";
import "./visitor-parking-new-reservation-card-editor";

type HassEntity = {
  state: string;
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

type VisitorParkingNewReservationCardConfig = {
  type: string;
  title?: string;
  config_entry_id?: string;
  favorites_entity?: string;
};

type Favorite = {
  id?: number | string;
  name?: string;
  license_plate?: string;
};

@customElement("visitor-parking-new-reservation-card")
export class VisitorParkingNewReservationCard extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @state() private _config?: VisitorParkingNewReservationCardConfig;

  @state() private _favoriteDraft = "";
  @state() private _nameDraft = "";
  @state() private _licensePlateDraft = "";
  @state() private _addToFavorites = false;
  @state() private _updateFavorite = false;
  @state() private _submitting = false;
  @state() private _deletingFavorite = false;
  @state() private _updatingFavorite = false;
  @state() private _resolvingService = false;
  @state() private _resolvedConfigEntryId?: string;
  @state() private _resolvedIdentifier?: string;
  @state() private _entries: ConfigEntrySummary[] = [];
  @state() private _entriesLoaded = false;
  @state() private _entityRegistry: EntityRegistryEntry[] = [];
  @state() private _entityRegistryLoaded = false;
  @state() private _selectedEntryId?: string;
  private _lastResolveAttempt?: number;
  private _lastResolveEntryId?: string;

  public setConfig(config: VisitorParkingNewReservationCardConfig): void {
    this._config = config;
  }

  protected updated(changedProps: Map<string, unknown>) {
    if (!this.hass || !this._config) return;

    const favoritesEntity = (this._config.favorites_entity ?? "").trim();
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

    const entryId = this._activeEntryId;
    if (!entryId || favoritesEntity) return;
    const identifier = this._entryIdentifier(entryId);
    if (identifier) {
      this._resolvedIdentifier = identifier;
      this._resolvedConfigEntryId = entryId;
      return;
    }
    if (!this.hass.user?.is_admin) return;
    if (!this.hass.callWS) return;

    const prevConfig = changedProps.get("_config") as
      | VisitorParkingNewReservationCardConfig
      | undefined;
    const entryIdChanged =
      changedProps.has("_config") && prevConfig?.config_entry_id !== entryId;
    if (entryIdChanged) {
      this._resolvedConfigEntryId = undefined;
      this._resolvedIdentifier = undefined;
      this._lastResolveAttempt = undefined;
      this._lastResolveEntryId = undefined;
    }

    if (this._resolvingService) return;

    const shouldResolve = this._resolvedConfigEntryId !== entryId;
    if (!shouldResolve) return;

    const now = Date.now();
    const lastAttemptRelevant = this._lastResolveEntryId === entryId;
    const retryDue =
      !lastAttemptRelevant ||
      this._lastResolveAttempt === undefined ||
      now - this._lastResolveAttempt > 30_000;
    if (!retryDue) return;

    this._lastResolveAttempt = now;
    this._lastResolveEntryId = entryId;
    void this._resolveIdFromConfigEntry(entryId);
  }

  private async _resolveIdFromConfigEntry(entryId: string): Promise<void> {
    if (!this.hass?.callWS) return;
    this._resolvingService = true;
    try {
      const resolved = await resolveIdFromConfigEntry(
        this.hass,
        entryId
      );
      if (resolved) {
        this._resolvedIdentifier = resolved;
        this._resolvedConfigEntryId = entryId;
      } else {
        this._resolvedIdentifier = undefined;
        this._resolvedConfigEntryId = undefined;
      }
    } catch (_err) {
      this._resolvedIdentifier = undefined;
      this._resolvedConfigEntryId = undefined;
    } finally {
      this._resolvingService = false;
    }
  }

  public static getConfigElement(): HTMLElement {
    return document.createElement("visitor-parking-new-reservation-card-editor");
  }

  public static getStubConfig(): VisitorParkingNewReservationCardConfig {
    return {
      type: "custom:visitor-parking-new-reservation-card",
    };
  }

  public getCardSize(): number {
    return 4;
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
      if (
        !this._config?.config_entry_id &&
        !this._selectedEntryId &&
        this._entries.length === 1
      ) {
        this._setSelectedEntry(this._entries[0].entry_id);
      }
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

  private _setSelectedEntry(entryId: string | undefined): void {
    this._selectedEntryId = entryId;
    this._resolvedConfigEntryId = undefined;
    this._resolvedIdentifier = undefined;
    this._lastResolveAttempt = undefined;
    this._lastResolveEntryId = undefined;
    this._favoriteDraft = "";
    this._nameDraft = "";
    this._licensePlateDraft = "";
    this._addToFavorites = false;
    this._updateFavorite = false;
  }

  private get _activeEntryId(): string | undefined {
    if (this._config?.config_entry_id) return this._config.config_entry_id;
    if (this._selectedEntryId) return this._selectedEntryId;
    if (this._entriesLoaded && this._entries.length === 1) {
      return this._entries[0].entry_id;
    }
    return undefined;
  }

  private _entryIdentifier(entryId: string | undefined): string | undefined {
    if (!entryId) return undefined;
    const entry = this._entries.find((item) => item.entry_id === entryId);
    return entry ? resolveIdentifierFromEntry(entry) : undefined;
  }

  private get _slug(): string | undefined {
    const entryId = this._activeEntryId;
    if (!entryId) return undefined;
    const identifier = this._entryIdentifier(entryId);
    if (identifier) return identifier;
    if (this._resolvedConfigEntryId === entryId && this._resolvedIdentifier) {
      return this._resolvedIdentifier;
    }
    return undefined;
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

  private get _favoritesEntityId(): string | undefined {
    const override = (this._config?.favorites_entity ?? "").trim();
    if (override && this._state(override)) return override;

    const slug = this._slug;
    const registryEntity = this._favoritesEntityFromRegistry();
    if (registryEntity) return registryEntity;

    if (!slug) {
      return undefined;
    }

    const slugId = slugifyId(slug);
    return `sensor.visitor_parking_${slugId}_favorites`;
  }

  private _favoritesEntityFromRegistry(): string | undefined {
    const entryId = this._activeEntryId;
    if (!entryId || !this._entityRegistryLoaded) return undefined;
    const entry = this._entityRegistry.find(
      (item) =>
        item.config_entry_id === entryId &&
        item.entity_id.startsWith("sensor.") &&
        item.entity_id.endsWith("_favorites")
    );
    return entry?.entity_id;
  }

  private _state(entityId?: string): HassEntity | undefined {
    return entityId && this.hass ? this.hass.states[entityId] : undefined;
  }

  private get _favoritesState(): HassEntity | undefined {
    return this._state(this._favoritesEntityId);
  }

  private get _favorites(): Favorite[] {
    const favorites = this._favoritesState?.attributes?.favorites;
    return Array.isArray(favorites)
      ? (favorites as Favorite[])
      : [];
  }

  private _favoriteLabel(favorite: Favorite): string {
    const name = (favorite.name ?? "").trim();
    const plate = (favorite.license_plate ?? "").trim();
    if (name && plate) return `${name} - ${plate}`;
    return (
      name ||
      plate ||
      localize(this.hass, "new_reservation_card.favorite_fallback_label")
    );
  }

  private _normalizeName(value: string): string {
    return value.trim().toLowerCase();
  }

  private _normalizePlate(value: string): string {
    return value.trim().toUpperCase().replaceAll(/[^A-Z0-9]/g, "");
  }

  private _favoriteMatchesDraft(favorite: Favorite, name: string, plate: string): boolean {
    return (
      this._normalizeName(favorite.name ?? "") === this._normalizeName(name) &&
      this._normalizePlate(favorite.license_plate ?? "") === this._normalizePlate(plate)
    );
  }

  private _findFavoriteIndexByDraft(name: string, plate: string): number | undefined {
    if (!name.trim() || !plate.trim()) return undefined;
    const favorites = this._favorites;
    for (let i = 0; i < favorites.length; i++) {
      if (this._favoriteMatchesDraft(favorites[i], name, plate)) return i;
    }
    return undefined;
  }

  private get _selectedFavoriteIndex(): number | undefined {
    const indexValue = this._favoriteDraft;
    if (!indexValue) return undefined;

    const index = Number(indexValue);
    if (!Number.isFinite(index) || index < 0 || index >= this._favorites.length) {
      return undefined;
    }

    return index;
  }

  private get _selectedFavorite(): Favorite | undefined {
    const index = this._selectedFavoriteIndex;
    return index !== undefined ? this._favorites[index] : undefined;
  }

  private get _selectedFavoriteId(): string | undefined {
    const id = this._selectedFavorite?.id;
    if (typeof id === "number" && Number.isFinite(id)) return String(id);
    if (typeof id === "string" && id.trim() !== "") return id.trim();
    return undefined;
  }

  private get _busy(): boolean {
    return this._submitting || this._deletingFavorite || this._updatingFavorite;
  }

  private get _draftMatchesExistingFavorite(): boolean {
    return (
      this._findFavoriteIndexByDraft(this._nameDraft, this._licensePlateDraft) !==
      undefined
    );
  }

  private get _showAddToFavorites(): boolean {
    if (!this._nameDraft.trim() || !this._licensePlateDraft.trim()) return false;
    if (this._selectedFavorite && !this._selectedFavoriteChangedBoth) return false;
    return !this._draftMatchesExistingFavorite;
  }

  private get _selectedFavoriteChanged(): boolean {
    const selected = this._selectedFavorite;
    if (!selected) return false;
    return !this._favoriteMatchesDraft(selected, this._nameDraft, this._licensePlateDraft);
  }

  private get _selectedFavoriteNameChanged(): boolean {
    const selected = this._selectedFavorite;
    if (!selected) return false;
    return (
      this._normalizeName(selected.name ?? "") !== this._normalizeName(this._nameDraft)
    );
  }

  private get _selectedFavoritePlateChanged(): boolean {
    const selected = this._selectedFavorite;
    if (!selected) return false;
    return (
      this._normalizePlate(selected.license_plate ?? "") !==
      this._normalizePlate(this._licensePlateDraft)
    );
  }

  private get _selectedFavoriteChangedBoth(): boolean {
    return this._selectedFavoriteNameChanged && this._selectedFavoritePlateChanged;
  }

  private _maybeResetFavoriteSelection(): void {
    if (!this._selectedFavorite) return;

    if (!this._selectedFavoriteChangedBoth) return;

    this._favoriteDraft = "";
    this._updateFavorite = false;
  }

  private get _draftDuplicatesOtherFavorite(): boolean {
    const selectedIndex = this._selectedFavoriteIndex;
    if (selectedIndex === undefined) return false;
    const matchingIndex = this._findFavoriteIndexByDraft(
      this._nameDraft,
      this._licensePlateDraft
    );
    return matchingIndex !== undefined && matchingIndex !== selectedIndex;
  }

  private get _offerUpdateFavorite(): boolean {
    if (!this._selectedFavorite) return false;
    return this._selectedFavoriteChanged && !this._selectedFavoriteChangedBoth;
  }

  private get _canUpdateFavorite(): boolean {
    if (!this._offerUpdateFavorite) return false;
    if (!this._nameDraft.trim() || !this._licensePlateDraft.trim()) return false;
    return !this._draftDuplicatesOtherFavorite;
  }

  private _syncFavoriteToggles(): void {
    if (this._selectedFavorite) {
      if (!this._showAddToFavorites) {
        this._addToFavorites = false;
      }
      if (!this._canUpdateFavorite) {
        this._updateFavorite = false;
      }
      return;
    }

    this._updateFavorite = false;
    if (!this._showAddToFavorites) {
      this._addToFavorites = false;
    }
  }

  private _selectFavorite(indexValue: string): void {
    this._favoriteDraft = indexValue;
    this._addToFavorites = false;
    this._updateFavorite = false;
    if (!indexValue) {
      this._nameDraft = "";
      this._licensePlateDraft = "";
      this._syncFavoriteToggles();
      return;
    }

    const index = Number(indexValue);
    if (!Number.isFinite(index) || index < 0 || index >= this._favorites.length) return;

    const favorite = this._favorites[index];
    if (!favorite) return;

    this._nameDraft = (favorite.name ?? "").trim();
    this._licensePlateDraft = (favorite.license_plate ?? "").trim();
    this._syncFavoriteToggles();
  }

  private _entryChanged(ev: Event): void {
    const entryId = (ev.target as HTMLSelectElement).value || undefined;
    this._setSelectedEntry(entryId);
  }

  private async _deleteFavorite(): Promise<void> {
    if (!this.hass || !this._config) return;
    if (!this._activeEntryId && this._entriesLoaded && this._entries.length > 1) return;
    if (!this._selectedFavoriteId) return;

    this._deletingFavorite = true;
    try {
      await this.hass.callService("visitor_parking", "delete_favorite", {
        favorite_id: this._selectedFavoriteId,
        ...(this._activeEntryId && {
          config_entry_id: this._activeEntryId,
        }),
      });

      this._favoriteDraft = "";
      this._updateFavorite = false;
      this._syncFavoriteToggles();
    } catch (_err) {
      this._notify(localize(this.hass, "new_reservation_card.could_not_remove_favorite"));
    } finally {
      this._deletingFavorite = false;
    }
  }

  private async _submit(): Promise<void> {
    if (!this.hass || !this._config) return;
    if (!this._activeEntryId && this._entriesLoaded && this._entries.length > 1) return;

    const licensePlate = this._licensePlateDraft.trim();
    if (!licensePlate) {
      this._notify(localize(this.hass, "new_reservation_card.license_plate_required_error"));
      return;
    }

    const selectedFavoriteId = this._selectedFavoriteId;
    const shouldUpdateFavorite = Boolean(
      selectedFavoriteId &&
        this._updateFavorite &&
        this._canUpdateFavorite &&
        this._selectedFavoriteChanged
    );
    const shouldAddFavorite = Boolean(this._addToFavorites && this._showAddToFavorites);

    this._submitting = true;
    try {
      await this.hass.callService("visitor_parking", "create_reservation", {
        license_plate: licensePlate,
        ...(this._nameDraft.trim() && { name: this._nameDraft.trim() }),
        ...(this._activeEntryId && {
          config_entry_id: this._activeEntryId,
        }),
      });

      if (shouldUpdateFavorite) {
        if (!this._nameDraft.trim()) {
          this._notify(
            localize(this.hass, "new_reservation_card.favorite_name_required_error")
          );
        } else {
          this._updatingFavorite = true;
          try {
            await this.hass.callService("visitor_parking", "update_favorite", {
              favorite_id: selectedFavoriteId,
              name: this._nameDraft.trim(),
              license_plate: licensePlate,
              ...(this._activeEntryId && {
                config_entry_id: this._activeEntryId,
              }),
            });
          } catch (_err) {
            this._notify(
              localize(this.hass, "new_reservation_card.could_not_update_favorite")
            );
          } finally {
            this._updatingFavorite = false;
          }
        }
      } else if (shouldAddFavorite) {
        if (!this._nameDraft.trim()) {
          this._notify(
            localize(this.hass, "new_reservation_card.favorite_name_required_error")
          );
        } else {
          try {
            await this.hass.callService("visitor_parking", "create_favorite", {
              name: this._nameDraft.trim(),
              license_plate: licensePlate,
              ...(this._activeEntryId && {
                config_entry_id: this._activeEntryId,
              }),
            });
          } catch (_err) {
            this._notify(localize(this.hass, "new_reservation_card.could_not_save_favorite"));
          }
        }
      }

      this._favoriteDraft = "";
      this._nameDraft = "";
      this._licensePlateDraft = "";
      this._addToFavorites = false;
      this._updateFavorite = false;
    } catch (_err) {
      this._notify(localize(this.hass, "new_reservation_card.could_not_submit"));
    } finally {
      this._submitting = false;
    }
  }

  protected render() {
    if (!this.hass || !this._config) return nothing;

    const title =
      this._config.title ?? localize(this.hass, "new_reservation_card.default_title");
    const entryId = this._activeEntryId;
    const showEntryPicker =
      !this._config.config_entry_id && this._entriesLoaded && this._entries.length > 1;
    const missingEntrySelection = showEntryPicker && !entryId;
    const favoritesState = this._favoritesState;
    const missingFavorites =
      Boolean(entryId) &&
      (!favoritesState ||
        favoritesState.state === "unavailable" ||
        favoritesState.state === "unknown");
    const showMissingFavoritesWarning =
      Boolean(entryId) && !this._resolvingService && missingFavorites;
    const canDeleteFavorite = Boolean(this._selectedFavoriteId);
    const showDeleteFavorite =
      canDeleteFavorite && !this._offerUpdateFavorite && !this._showAddToFavorites;
    const entryLocked = missingEntrySelection;
    const submitLabel = this._submitting
      ? localize(this.hass, "common.working")
      : localize(this.hass, "new_reservation_card.check_in");

    return html`
      <ha-card header=${title}>
        <div class="card-content">
          ${showEntryPicker
            ? html`<div class="field">
                <div class="label">
                  ${localize(this.hass, "new_reservation_card.service")}
                </div>
                <select
                  class="select"
                  .value=${entryId ?? ""}
                  @change=${this._entryChanged}
                >
                  <option value="">
                    ${localize(this.hass, "new_reservation_card.service_placeholder")}
                  </option>
                  ${this._entries.map(
                    (entry) =>
                      html`<option .value=${entry.entry_id}>
                        ${entry.title}
                      </option>`
                  )}
                </select>
              </div>`
            : nothing}
          ${entryId && this._resolvingService
            ? html`<div class="empty">${localize(this.hass, "common.working")}</div>`
            : nothing}
          ${showMissingFavoritesWarning
            ? html`<div class="warning">
                ${localize(this.hass, "new_reservation_card.missing_favorites_warning")}
              </div>`
            : nothing}

          <div class="field">
            <div class="label">${localize(this.hass, "new_reservation_card.favorites")}</div>
            <select
              class="select"
              .value=${this._favoriteDraft}
              ?disabled=${missingFavorites || entryLocked || this._busy}
              @change=${(ev: Event) =>
                this._selectFavorite((ev.target as HTMLSelectElement).value)}
            >
              <option value="">${localize(this.hass, "common.dash")}</option>
              ${this._favorites.map(
                (favorite, index) =>
                  html`<option .value=${String(index)}>
                    ${this._favoriteLabel(favorite)}
                  </option>`
              )}
            </select>
          </div>

          <div class="field">
            <div class="label">${localize(this.hass, "new_reservation_card.name")}</div>
            <input
              class="input"
              type="text"
              .value=${this._nameDraft}
              ?disabled=${entryLocked || this._busy}
              @input=${(ev: Event) => {
                this._nameDraft = (ev.target as HTMLInputElement).value;
                this._maybeResetFavoriteSelection();
                this._syncFavoriteToggles();
              }}
            />
          </div>

          <div class="field">
            <div class="label">
              ${localize(this.hass, "new_reservation_card.license_plate_required")}
            </div>
            <input
              class="input"
              type="text"
              required
              .value=${this._licensePlateDraft}
              ?disabled=${entryLocked || this._busy}
              @input=${(ev: Event) => {
                this._licensePlateDraft = (ev.target as HTMLInputElement).value;
                this._maybeResetFavoriteSelection();
                this._syncFavoriteToggles();
              }}
            />
          </div>

          <div class="row">
            ${this._offerUpdateFavorite
              ? html`
                  <label class="switch-row">
                    <input
                      type="checkbox"
                      .checked=${this._updateFavorite}
                      ?disabled=${entryLocked || this._busy || !this._canUpdateFavorite}
                      @change=${(ev: Event) => {
                        this._updateFavorite = (ev.target as HTMLInputElement).checked;
                      }}
                    />
                    <span>
                      ${localize(this.hass, "new_reservation_card.update_favorite")}
                    </span>
                  </label>
                `
              : showDeleteFavorite
              ? html`
                  <div class="switch-row">
                    <button
                      type="button"
                      class="icon-button"
                      aria-label=${localize(
                        this.hass,
                        "new_reservation_card.remove_favorite"
                      )}
                      ?disabled=${entryLocked || this._busy}
                      @click=${this._deleteFavorite}
                    >
                      <ha-icon icon="mdi:delete" class="danger-icon"></ha-icon>
                    </button>
                    <span>
                      ${localize(this.hass, "new_reservation_card.remove_favorite")}
                    </span>
                  </div>
                `
              : this._showAddToFavorites
                ? html`
                    <label class="switch-row">
                      <input
                        type="checkbox"
                        .checked=${this._addToFavorites}
                        ?disabled=${entryLocked || this._busy}
                        @change=${(ev: Event) => {
                          this._addToFavorites = (ev.target as HTMLInputElement).checked;
                        }}
                      />
                      <span>
                        ${localize(this.hass, "new_reservation_card.add_to_favorites")}
                      </span>
                    </label>
                  `
                : html`<div></div>`}

            <ha-button
              appearance="filled"
              .disabled=${entryLocked || this._busy || !this._licensePlateDraft.trim()}
              @click=${this._submit}
            >
              ${submitLabel}
            </ha-button>
          </div>
        </div>
      </ha-card>
    `;
  }

  static styles = css`
    .card-content {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .warning {
      color: var(--error-color);
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .label {
      font-weight: 500;
    }

    .input,
    .select {
      border: 1px solid var(--divider-color);
      border-radius: var(--ha-card-border-radius, 12px);
      background-color: var(--card-background-color);
      color: var(--primary-text-color);
      padding: 10px 12px;
      min-height: 40px;
      height: 40px;
      box-sizing: border-box;
    }

    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .switch-row {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-height: 40px;
      height: 40px;
      box-sizing: border-box;
    }

    .icon-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 16px;
      background-color: var(--card-background-color);
      border: none;
      padding: 0;
      font: inherit;
      line-height: 0;
      cursor: pointer;
    }

    .danger-icon {
      width: 16px;
      height: 16px;
      color: var(--error-color);
      --mdc-icon-size: 16px;
      --ha-icon-size: 16px;
    }

    .icon-button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  `;
}

(window as any).customCards ??= [];
(window as any).customCards.push({
  type: "visitor-parking-new-reservation-card",
  name: localizeLanguage(
    globalThis.navigator?.language,
    "new_reservation_card.card_name"
  ),
  description: localizeLanguage(
    globalThis.navigator?.language,
    "new_reservation_card.card_description"
  ),
  editor: "visitor-parking-new-reservation-card-editor",
});

declare global {
  interface HTMLElementTagNameMap {
    "visitor-parking-new-reservation-card": VisitorParkingNewReservationCard;
  }
}
