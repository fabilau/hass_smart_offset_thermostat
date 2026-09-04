"""Smart Offset Thermostat integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CLIMATE,
    CONF_RECOVERY_DEVICE_ID,
    CONF_RECOVERY_FINGERPRINT,
    CONF_RECOVERY_SOURCE_ENTRY_ID,
    CONF_REGISTRY_IDENTITY,
    CONF_ROOM_SENSOR,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    PLATFORMS,
    entry_registry_identity,
)
from .controller import SmartOffsetController
from .migration import (
    integration_disabled_entity_ids,
    migrate_config_entry_payload,
    select_source_entry_owner,
)
from .recovery import (
    RegistryRecoveryError,
    adopt_orphaned_registry_group,
    verify_recovered_registry_group,
)
from .storage import OffsetStorage

LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_STORAGE_LOAD_TASK = "_storage_load_task"


def _legacy_entry_unique_id(
    hass: HomeAssistant, entry: ConfigEntry, data: dict
) -> str | None:
    """Return a safe source-based unique ID for a legacy config entry."""
    if entry.unique_id is not None:
        return None
    source = data.get(CONF_CLIMATE)
    if not isinstance(source, str) or not (source := source.strip()):
        return None
    existing = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, source)
    if existing is not None and existing.entry_id != entry.entry_id:
        return None
    return source


def _restore_integration_disabled_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> int:
    """Re-enable entities disabled by the 2.0.0/2.0.1 defaults.

    Registry choices made by the user, device or parent config entry remain
    untouched. The user's explicit preference to disable newly added entities
    also wins over this compatibility repair.
    """
    registry = er.async_get(hass)
    entity_ids = integration_disabled_entity_ids(
        er.async_entries_for_config_entry(registry, entry.entry_id),
        entry.entry_id,
    )
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    return len(entity_ids)


async def _async_get_storage(hass: HomeAssistant) -> OffsetStorage:
    """Return the single shared store, even during parallel entry setup."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    existing = domain_data.get("storage")
    if existing is not None:
        return existing

    load_task = domain_data.get(_STORAGE_LOAD_TASK)
    if load_task is None:

        async def _load() -> OffsetStorage:
            store = OffsetStorage(hass)
            await store.async_load()
            return store

        # Assign before yielding so every concurrently starting entry awaits
        # the same instance and cannot overwrite another entry's runtime data.
        load_task = hass.async_create_task(_load())
        domain_data[_STORAGE_LOAD_TASK] = load_task

    try:
        store = await load_task
    except Exception:
        if domain_data.get(_STORAGE_LOAD_TASK) is load_task:
            domain_data.pop(_STORAGE_LOAD_TASK, None)
        raise
    domain_data["storage"] = store
    if domain_data.get(_STORAGE_LOAD_TASK) is load_task:
        domain_data.pop(_STORAGE_LOAD_TASK, None)
    return store


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration namespace."""
    await _async_get_storage(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config-entry data without losing user configuration."""
    version = int(entry.version or 1)
    minor_version = int(getattr(entry, "minor_version", 0) or 0)
    # Minor versions are backward compatible in Home Assistant. A newer
    # minor payload must remain untouched, while a newer major is unsafe.
    if version > CONFIG_ENTRY_VERSION:
        LOGGER.error(
            "Cannot migrate config entry %s from future version %s.%s",
            entry.entry_id,
            version,
            minor_version,
        )
        return False
    if version == CONFIG_ENTRY_VERSION and minor_version > CONFIG_ENTRY_MINOR_VERSION:
        # Minor config-entry versions are backward compatible. Do not rewrite
        # or downgrade an entry produced by a newer integration build.
        return True

    # Schema 3.5 is the one-shot marker for undoing entity defaults shipped in
    # 2.0.0/2.0.1. It intentionally revisits 3.4 because that repair used the
    # config-entry preference for new entities as an overly broad guard and
    # could therefore leave existing registry rows disabled.
    # Keeping this inside migration prevents a future deliberately disabled
    # diagnostic entity from being re-enabled on every normal reload.
    restored_entities = 0
    # The regression repair belongs specifically to upgrades from before
    # schema 3.5. Keep that boundary fixed so a future schema bump cannot
    # accidentally re-enable entities that are disabled by design later on.
    if version < 3 or (version == 3 and minor_version < 5):
        restored_entities = _restore_integration_disabled_entities(hass, entry)

    data, options, changed = migrate_config_entry_payload(
        dict(entry.data),
        dict(entry.options),
        version,
        minor_version,
    )
    unique_id = _legacy_entry_unique_id(hass, entry, data)
    if changed or unique_id is not None:
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            unique_id=unique_id if unique_id is not None else entry.unique_id,
            version=CONFIG_ENTRY_VERSION,
            minor_version=CONFIG_ENTRY_MINOR_VERSION,
        )
        LOGGER.info(
            "Migrated config entry %s from %s.%s to %s.%s",
            entry.entry_id,
            version,
            minor_version,
            CONFIG_ENTRY_VERSION,
            CONFIG_ENTRY_MINOR_VERSION,
        )
    if restored_entities:
        LOGGER.info(
            "Re-enabled %s entities disabled by the 2.0 UI defaults for %s",
            restored_entities,
            entry.entry_id,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Offset Thermostat from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    # Home Assistant normally invokes async_migrate_entry before setup. Keep a
    # defensive repair here as well for restored backups or intermediate builds
    # that already carry the current schema marker but a split data/options
    # payload. This preserves the entry_id and therefore every existing entity.
    missing_sources = [
        key
        for key in (CONF_CLIMATE, CONF_ROOM_SENSOR)
        if not isinstance(entry.data.get(key), str) or not entry.data.get(key).strip()
    ]
    if missing_sources:
        data, options, changed = migrate_config_entry_payload(
            dict(entry.data),
            dict(entry.options),
            int(entry.version or 1),
            int(getattr(entry, "minor_version", 0) or 0),
        )
        if changed:
            hass.config_entries.async_update_entry(
                entry,
                data=data,
                options=options,
            )
        missing_sources = [
            key
            for key in (CONF_CLIMATE, CONF_ROOM_SENSOR)
            if not isinstance(entry.data.get(key), str)
            or not entry.data.get(key).strip()
        ]
    if missing_sources:
        raise ConfigEntryError(
            "Config entry is missing required source entities: "
            + ", ".join(missing_sources)
        )

    # Prefer the original entry so entity IDs already used by dashboards and
    # automations survive.  A controller that is already loaded keeps priority
    # so a later reload can never start a second controller for the same valve.
    owner = select_source_entry_owner(hass.config_entries.async_entries(DOMAIN), entry)
    if owner.entry_id != entry.entry_id:
        raise ConfigEntryError(
            "Physical thermostat "
            f"{entry.data[CONF_CLIMATE]} is already controlled by config entry "
            f"{owner.title!r} ({owner.entry_id}); remove the duplicate entry "
            "or reconfigure it to another thermostat"
        )

    if unique_id := _legacy_entry_unique_id(hass, entry, dict(entry.data)):
        hass.config_entries.async_update_entry(entry, unique_id=unique_id)

    storage = await _async_get_storage(hass)

    recovery_fields = (
        CONF_RECOVERY_SOURCE_ENTRY_ID,
        CONF_RECOVERY_DEVICE_ID,
        CONF_RECOVERY_FINGERPRINT,
    )
    recovery_values = {key: entry.data.get(key) for key in recovery_fields}
    recovery_pending: dict | None = None
    restored_entities = 0
    if any(value is not None for value in recovery_values.values()):
        if any(
            not isinstance(value, str) or not value
            for value in recovery_values.values()
        ) or not isinstance(entry.data.get(CONF_REGISTRY_IDENTITY), str):
            raise ConfigEntryError("Registry recovery metadata is incomplete")

        source_entry_id = recovery_values[CONF_RECOVERY_SOURCE_ENTRY_ID]
        device_id = recovery_values[CONF_RECOVERY_DEVICE_ID]
        fingerprint = recovery_values[CONF_RECOVERY_FINGERPRINT]
        registry_identity = entry_registry_identity(entry)
        assert isinstance(source_entry_id, str)
        assert isinstance(device_id, str)
        assert isinstance(fingerprint, str)

        identity_owners: dict[str, str] = {}
        for candidate in hass.config_entries.async_entries(DOMAIN):
            identity = entry_registry_identity(candidate)
            previous_owner = identity_owners.get(identity)
            if previous_owner is not None and previous_owner != candidate.entry_id:
                raise ConfigEntryError(
                    f"Registry identity {identity!r} is owned by multiple entries"
                )
            identity_owners[identity] = candidate.entry_id

        try:
            # Keep a crash-safe copy under both entry IDs until the registry
            # has been restored and verified after platform forwarding.
            storage.validate_entry_adoption(source_entry_id, entry.entry_id)
            await storage.async_prepare_entry_adoption(source_entry_id, entry.entry_id)
            result = adopt_orphaned_registry_group(
                er.async_get(hass),
                dr.async_get(hass),
                source_entry_id=source_entry_id,
                new_entry_id=entry.entry_id,
                registry_identity=registry_identity,
                device_id=device_id,
                fingerprint=fingerprint,
                configured_entry_ids=(
                    candidate.entry_id
                    for candidate in hass.config_entries.async_entries(DOMAIN)
                ),
                claimed_registry_identities=identity_owners,
            )
        except RegistryRecoveryError as err:
            raise ConfigEntryError(
                f"Registry recovery failed ({err.reason}): {err}"
            ) from err
        except RuntimeError as err:
            raise ConfigEntryError(
                f"Registry recovery failed (storage_conflict): {err}"
            ) from err
        except Exception as err:
            # Registry operations are wrapped above, so an exception reaching
            # here is an unexpected storage persistence failure. Keep the
            # recovery markers in place and retry the idempotent adoption on
            # the next setup instead of loading with unpersisted runtime data.
            raise ConfigEntryError(
                f"Registry recovery failed (storage_write): {err}"
            ) from err

        recovery_pending = {
            "source_entry_id": source_entry_id,
            "device_id": device_id,
            "registry_identity": registry_identity,
            "expected_entity_count": result.entity_count,
        }
        if not result.tombstoned:
            # Active rows can be repaired before forwarding so every entity is
            # instantiated in this setup pass. Tombstones become active during
            # forwarding and receive the same repair immediately afterwards.
            restored_entities += _restore_integration_disabled_entities(hass, entry)

    controller = SmartOffsetController(hass, entry, storage)
    domain_data[entry.entry_id] = controller

    async def _async_cleanup_failed_setup() -> None:
        """Best-effort cleanup that never hides the original setup error."""
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception:
            LOGGER.exception(
                "Failed to unload platforms after setup failure for %s",
                entry.entry_id,
            )
        try:
            await controller.async_stop()
        except Exception:
            LOGGER.exception(
                "Failed to stop controller after setup failure for %s",
                entry.entry_id,
            )
        domain_data.pop(entry.entry_id, None)

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if recovery_pending is not None:
            newly_restored = _restore_integration_disabled_entities(hass, entry)
            restored_entities += newly_restored
            if newly_restored:
                # Tombstones remember integration-disabled defaults. They are
                # only visible to repair after the first native resurrection,
                # so reload the just-forwarded platforms once to instantiate
                # the newly enabled entities in this same setup transaction.
                if not await hass.config_entries.async_unload_platforms(
                    entry, PLATFORMS
                ):
                    raise ConfigEntryError(
                        "Registry recovery could not reload restored entities"
                    )
                await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
            verified = verify_recovered_registry_group(
                er.async_get(hass),
                dr.async_get(hass),
                new_entry_id=entry.entry_id,
                registry_identity=recovery_pending["registry_identity"],
                device_id=recovery_pending["device_id"],
                expected_entity_count=recovery_pending["expected_entity_count"],
            )
            await storage.async_finalize_entry_adoption(
                recovery_pending["source_entry_id"], entry.entry_id
            )

            # Markers are the final commit record. If any earlier phase fails,
            # they remain and the idempotent recovery resumes on next setup.
            recovered_data = dict(entry.data)
            for key in recovery_fields:
                recovered_data.pop(key, None)
            hass.config_entries.async_update_entry(entry, data=recovered_data)
            LOGGER.info(
                "Recovered %s registry entities and %s device for %s; "
                "restored %s integration-disabled entities",
                verified.entity_count,
                verified.device_count,
                entry.entry_id,
                restored_entities,
            )
        await controller.async_start()
    except RegistryRecoveryError as err:
        await _async_cleanup_failed_setup()
        raise ConfigEntryError(
            f"Registry recovery failed ({err.reason}): {err}"
        ) from err
    except Exception:
        await _async_cleanup_failed_setup()
        raise

    async def _async_entry_updated(
        _hass: HomeAssistant, updated_entry: ConfigEntry
    ) -> None:
        current = hass.data.get(DOMAIN, {}).get(updated_entry.entry_id)
        if current is not None:
            await current.async_options_updated()

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and every listener owned by its controller."""
    controller = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if controller is not None:
            await controller.async_stop()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persisted state belonging to a deleted config entry."""
    store = await _async_get_storage(hass)
    await store.async_remove_entry(entry.entry_id)
