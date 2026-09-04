"""Safe recovery of registry entries whose config entry was lost."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN


class RegistryRecoveryError(ValueError):
    """Raised when an orphaned registry group cannot be adopted safely."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


@dataclass(frozen=True, slots=True)
class OrphanedRegistryGroup:
    """One recoverable group left behind by a missing config entry."""

    source_entry_id: str
    registry_identity: str
    device_id: str
    fingerprint: str
    label: str
    entity_count: int
    area_id: str | None = None
    tombstoned: bool = False


@dataclass(frozen=True, slots=True)
class RegistryRecoveryResult:
    """Summary of a completed or resumed registry adoption."""

    entity_count: int
    device_count: int
    already_adopted: bool = False
    tombstoned: bool = False


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _clean_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    # Registry names are user-controlled. Keep labels single-line and compact;
    # the Home Assistant frontend performs the remaining escaping.
    cleaned = " ".join(value.split()).strip()
    return cleaned[:100] if cleaned else None


def _entity_suffix(entity: Any, registry_identity: str) -> str | None:
    unique_id = getattr(entity, "unique_id", None)
    prefix = f"{registry_identity}_"
    if not isinstance(unique_id, str) or not unique_id.startswith(prefix):
        return None
    suffix = unique_id[len(prefix) :]
    return suffix if suffix else None


def _entity_fingerprint_row(entity: Any) -> list[Any]:
    """Return stable fields that identify one registry row during a flow."""
    return [
        str(getattr(entity, "id", "")),
        str(getattr(entity, "domain", "")),
        str(getattr(entity, "platform", "")),
        str(getattr(entity, "unique_id", "")),
        getattr(entity, "config_subentry_id", None),
    ]


def _fingerprint(
    source_entry_id: str,
    registry_identity: str,
    device_id: str,
    entities: Iterable[Any],
) -> str:
    payload = {
        "v": 2,
        "lost_entry_id": source_entry_id,
        "registry_identity": registry_identity,
        "device_id": device_id,
        "entities": sorted(
            (_entity_fingerprint_row(entity) for entity in entities),
            key=lambda row: tuple(str(value) for value in row),
        ),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _device_owners(device: Any) -> set[str]:
    return {str(owner) for owner in getattr(device, "config_entries", set())}


def _domain_identities(device: Any) -> set[str]:
    return {
        str(value)
        for domain, value in getattr(device, "identifiers", set())
        if domain == DOMAIN and value
    }


def _registry_entities(registry: Any) -> list[Any]:
    entities = getattr(registry, "entities", {})
    return list(entities.values() if hasattr(entities, "values") else entities)


def _registry_devices(registry: Any) -> list[Any]:
    devices = getattr(registry, "devices", {})
    return list(devices.values() if hasattr(devices, "values") else devices)


def _registry_deleted_entities(registry: Any) -> list[Any]:
    entities = getattr(registry, "deleted_entities", {})
    return list(entities.values() if hasattr(entities, "values") else entities)


def _registry_deleted_devices(registry: Any) -> list[Any]:
    devices = getattr(registry, "deleted_devices", {})
    return list(devices.values() if hasattr(devices, "values") else devices)


def _group_label(
    device: Any,
    anchor: Any,
    area_names: Mapping[str, str],
) -> tuple[str, str | None]:
    """Return a friendly label without exposing registry identifiers."""
    area_id = getattr(device, "area_id", None)
    if area_id is None:
        area_id = getattr(anchor, "area_id", None)
    area_id = str(area_id) if area_id is not None else None
    area_name = _clean_label(area_names.get(area_id)) if area_id else None
    device_name_by_user = _clean_label(getattr(device, "name_by_user", None))
    device_name = _clean_label(getattr(device, "name", None))
    anchor_name = _clean_label(
        getattr(anchor, "name", None) or getattr(anchor, "original_name", None)
    )
    generic_device_name = bool(
        device_name
        and device_name.casefold() in {"smart offset thermostat", "smart thermostat"}
    )
    label = (
        device_name_by_user
        or (device_name if not generic_device_name else None)
        or (f"Smart Offset Thermostat · {area_name}" if area_name is not None else None)
        or device_name
        or anchor_name
        or "Smart Offset Thermostat"
    )
    return label, area_id


def _candidate_group(
    source_entry_id: str,
    entities: list[Any],
    devices_by_id: Mapping[str, Any],
    claimed_identities: set[str],
    area_names: Mapping[str, str],
) -> OrphanedRegistryGroup | None:
    """Validate one owner group without exposing ambiguous registry data."""
    if not entities or any(
        getattr(entity, "platform", None) != DOMAIN
        or getattr(entity, "config_subentry_id", None) is not None
        for entity in entities
    ):
        return None

    device_ids = {
        str(entity.device_id)
        for entity in entities
        if getattr(entity, "device_id", None) is not None
    }
    if len(device_ids) != 1 or any(
        getattr(entity, "device_id", None) is None for entity in entities
    ):
        return None
    device_id = next(iter(device_ids))
    device = devices_by_id.get(device_id)
    if device is None or _device_owners(device) != {source_entry_id}:
        return None

    identities = _domain_identities(device)
    if len(identities) != 1:
        return None
    registry_identity = next(iter(identities))
    if registry_identity in claimed_identities:
        return None
    if any(_entity_suffix(entity, registry_identity) is None for entity in entities):
        return None

    anchors = [
        entity
        for entity in entities
        if getattr(entity, "domain", None) == "climate"
        and getattr(entity, "unique_id", None)
        == f"{registry_identity}_virtual_thermostat"
    ]
    if len(anchors) != 1:
        return None

    label, area_id = _group_label(device, anchors[0], area_names)

    return OrphanedRegistryGroup(
        source_entry_id=source_entry_id,
        registry_identity=registry_identity,
        device_id=device_id,
        fingerprint=_fingerprint(
            source_entry_id, registry_identity, device_id, entities
        ),
        label=label,
        entity_count=len(entities),
        area_id=area_id,
    )


def _candidate_tombstone_group(
    source_entry_id: str,
    entities: list[Any],
    device: Any,
    claimed_identities: set[str],
    area_names: Mapping[str, str],
) -> OrphanedRegistryGroup | None:
    """Validate one group retained by HA after missing-owner cleanup.

    Intentional config-entry removal clears the old owner and assigns an
    orphaned timestamp. Requiring the inverse on every row makes those normal
    deletions ineligible for recovery.
    """
    if not entities or any(
        getattr(entity, "platform", None) != DOMAIN
        or getattr(entity, "config_entry_id", None) != source_entry_id
        or getattr(entity, "config_subentry_id", None) is not None
        or getattr(entity, "orphaned_timestamp", None) is not None
        for entity in entities
    ):
        return None
    if (
        _device_owners(device) != {source_entry_id}
        or getattr(device, "orphaned_timestamp", None) is not None
    ):
        return None
    subentries = getattr(device, "config_entries_subentries", None)
    if subentries is not None and subentries != {source_entry_id: {None}}:
        return None

    identities = _domain_identities(device)
    if len(identities) != 1:
        return None
    registry_identity = next(iter(identities))
    if registry_identity in claimed_identities or any(
        _entity_suffix(entity, registry_identity) is None for entity in entities
    ):
        return None

    anchors = [
        entity
        for entity in entities
        if getattr(entity, "domain", None) == "climate"
        and getattr(entity, "unique_id", None)
        == f"{registry_identity}_virtual_thermostat"
    ]
    if len(anchors) != 1:
        return None

    device_id = str(getattr(device, "id", ""))
    if not device_id:
        return None
    label, area_id = _group_label(device, anchors[0], area_names)
    return OrphanedRegistryGroup(
        source_entry_id=source_entry_id,
        registry_identity=registry_identity,
        device_id=device_id,
        fingerprint=_fingerprint(
            source_entry_id,
            registry_identity,
            device_id,
            entities,
        ),
        label=label,
        entity_count=len(entities),
        area_id=area_id,
        tombstoned=True,
    )


def find_orphaned_registry_groups(
    entity_entries: Iterable[Any],
    device_entries: Iterable[Any],
    configured_entry_ids: Iterable[str],
    *,
    deleted_entity_entries: Iterable[Any] = (),
    deleted_device_entries: Iterable[Any] = (),
    claimed_registry_identities: Iterable[str] = (),
    area_names: Mapping[str, str] | None = None,
) -> list[OrphanedRegistryGroup]:
    """Return strictly validated Smart Offset groups without a config entry.

    Both live registry rows and HA's reversible deletion records are checked.
    The latter are only eligible while they still name the missing owner and
    have no orphan timestamp, which distinguishes cleanup from user deletion.
    """
    entities = list(entity_entries)
    deleted_entities = list(deleted_entity_entries)
    devices = list(device_entries)
    deleted_devices = list(deleted_device_entries)
    configured = {str(entry_id) for entry_id in configured_entry_ids}
    claimed = {str(identity) for identity in claimed_registry_identities}
    devices_by_id = {
        str(device.id): device
        for device in devices
        if getattr(device, "id", None) is not None
    }

    # Group by the missing owner. Registry identity is intentionally read from
    # the device because it may differ after a previous recovery (A → B → C).
    grouped: dict[str, list[Any]] = {}
    for entity in entities:
        owner = getattr(entity, "config_entry_id", None)
        if not isinstance(owner, str) or not owner or owner in configured:
            continue
        grouped.setdefault(owner, []).append(entity)

    active_candidates = [
        candidate
        for source_entry_id, group_entities in grouped.items()
        if (
            candidate := _candidate_group(
                source_entry_id,
                group_entities,
                devices_by_id,
                claimed,
                dict(area_names or {}),
            )
        )
        is not None
    ]

    deleted_grouped: dict[str, list[Any]] = {}
    for entity in deleted_entities:
        owner = getattr(entity, "config_entry_id", None)
        if not isinstance(owner, str) or not owner or owner in configured:
            continue
        deleted_grouped.setdefault(owner, []).append(entity)

    tombstone_candidates: list[OrphanedRegistryGroup] = []
    for source_entry_id, group_entities in deleted_grouped.items():
        matching_devices = [
            device
            for device in deleted_devices
            if _device_owners(device) == {source_entry_id}
        ]
        tombstone_candidates.extend(
            candidate
            for device in matching_devices
            if (
                candidate := _candidate_tombstone_group(
                    source_entry_id,
                    group_entities,
                    device,
                    claimed,
                    dict(area_names or {}),
                )
            )
            is not None
        )

    active_identities = {
        identity for device in devices for identity in _domain_identities(device)
    }
    tombstone_candidates = [
        candidate
        for candidate in tombstone_candidates
        if candidate.registry_identity not in active_identities
        and not any(
            getattr(entity, "platform", None) == DOMAIN
            and _entity_suffix(entity, candidate.registry_identity) is not None
            for entity in entities
        )
    ]
    candidates = [*active_candidates, *tombstone_candidates]

    identity_device_counts = Counter(
        identity
        for device in [*devices, *deleted_devices]
        for identity in _domain_identities(device)
    )
    candidates = [
        candidate
        for candidate in candidates
        if identity_device_counts[candidate.registry_identity] == 1
    ]

    # A shared identity or device makes both groups ambiguous. Do not offer a
    # destructive guess to the user.
    identity_counts = Counter(group.registry_identity for group in candidates)
    device_counts = Counter(group.device_id for group in candidates)
    candidates = [
        group
        for group in candidates
        if identity_counts[group.registry_identity] == 1
        and device_counts[group.device_id] == 1
    ]

    # No third owner may share the same stable identity prefix.
    safe: list[OrphanedRegistryGroup] = []
    all_identity_entities = [*entities, *deleted_entities]
    for group in candidates:
        if any(
            getattr(entity, "platform", None) == DOMAIN
            and _entity_suffix(entity, group.registry_identity) is not None
            and getattr(entity, "config_entry_id", None) != group.source_entry_id
            for entity in all_identity_entities
        ):
            continue
        safe.append(group)

    # Make duplicate friendly labels distinguishable without leaking IDs.
    label_counts = Counter(group.label for group in safe)
    label_indexes: Counter[str] = Counter()
    labelled: list[OrphanedRegistryGroup] = []
    for group in sorted(
        safe,
        key=lambda item: (item.label.casefold(), item.source_entry_id),
    ):
        label = group.label
        if label_counts[label] > 1:
            label_indexes[label] += 1
            label = f"{label} · {label_indexes[label]}"
        labelled.append(
            OrphanedRegistryGroup(
                source_entry_id=group.source_entry_id,
                registry_identity=group.registry_identity,
                device_id=group.device_id,
                fingerprint=group.fingerprint,
                label=label,
                entity_count=group.entity_count,
                area_id=group.area_id,
                tombstoned=group.tombstoned,
            )
        )
    return labelled


def adopt_orphaned_registry_group(
    entity_registry: Any,
    device_registry: Any,
    *,
    source_entry_id: str,
    new_entry_id: str,
    registry_identity: str,
    device_id: str,
    fingerprint: str,
    configured_entry_ids: Iterable[str],
    claimed_registry_identities: Mapping[str, str] | None = None,
) -> RegistryRecoveryResult:
    """Rebind one fingerprinted orphan while preserving every stable ID.

    All conflicts are checked before the first write. The write phases are
    synchronous and resumable: device gets the new owner first, entity owners
    change second, and the missing owner is removed from the device last.
    """
    if (
        not source_entry_id
        or not new_entry_id
        or source_entry_id == new_entry_id
        or not registry_identity
        or not device_id
        or not fingerprint
    ):
        raise RegistryRecoveryError("stale_group", "Invalid recovery metadata")

    configured = {str(entry_id) for entry_id in configured_entry_ids}
    if source_entry_id in configured:
        raise RegistryRecoveryError(
            "stale_group", "The original config entry still exists"
        )
    claimed = dict(claimed_registry_identities or {})
    identity_owner = claimed.get(registry_identity)
    if identity_owner is not None and identity_owner != new_entry_id:
        raise RegistryRecoveryError(
            "entity_conflict", "Registry identity belongs to another config entry"
        )

    device = device_registry.async_get(device_id)
    if device is None:
        identity_device = device_registry.async_get_device(
            identifiers={(DOMAIN, registry_identity)}
        )
        if identity_device is not None:
            raise RegistryRecoveryError(
                "device_conflict", "Registry identity resolves to another device"
            )

        # HA removes dangling active rows during startup, but retains reversible
        # tombstones. Do not mutate private registry internals: strict validation
        # here is sufficient because normal platform forwarding resurrects the
        # same device/entity IDs through async_get_or_create.
        other_claimed = {
            identity for identity, owner in claimed.items() if owner != new_entry_id
        }
        candidates = find_orphaned_registry_groups(
            _registry_entities(entity_registry),
            _registry_devices(device_registry),
            configured,
            deleted_entity_entries=_registry_deleted_entities(entity_registry),
            deleted_device_entries=_registry_deleted_devices(device_registry),
            claimed_registry_identities=other_claimed,
        )
        candidate = next(
            (
                item
                for item in candidates
                if item.tombstoned
                and item.source_entry_id == source_entry_id
                and item.registry_identity == registry_identity
                and item.device_id == device_id
                and item.fingerprint == fingerprint
            ),
            None,
        )
        if candidate is None:
            raise RegistryRecoveryError(
                "stale_group", "Recovery tombstones changed or are missing"
            )

        all_active = _registry_entities(entity_registry)
        if any(
            getattr(entity, "config_entry_id", None) in {source_entry_id, new_entry_id}
            for entity in all_active
        ):
            raise RegistryRecoveryError(
                "entity_conflict",
                "Config entry owns active entities outside the recovery tombstones",
            )
        return RegistryRecoveryResult(
            entity_count=candidate.entity_count,
            device_count=1,
            already_adopted=False,
            tombstoned=True,
        )
    if _domain_identities(device) != {registry_identity}:
        raise RegistryRecoveryError(
            "device_conflict", "Recovery device identity changed"
        )
    owners = _device_owners(device)
    if source_entry_id not in owners and new_entry_id not in owners:
        raise RegistryRecoveryError(
            "stale_group", "Recovery device no longer has an expected owner"
        )
    if owners - {source_entry_id, new_entry_id}:
        raise RegistryRecoveryError(
            "device_conflict", "Recovery device has an unexpected owner"
        )
    identity_device = device_registry.async_get_device(
        identifiers={(DOMAIN, registry_identity)}
    )
    if identity_device is None or identity_device.id != device_id:
        raise RegistryRecoveryError(
            "device_conflict", "Registry identity resolves to another device"
        )

    all_entities = _registry_entities(entity_registry)
    identity_entities = [
        entity
        for entity in all_entities
        if getattr(entity, "platform", None) == DOMAIN
        and _entity_suffix(entity, registry_identity) is not None
    ]
    if not identity_entities or any(
        getattr(entity, "device_id", None) != device_id for entity in identity_entities
    ):
        raise RegistryRecoveryError(
            "entity_conflict", "Registry identity spans multiple devices"
        )
    related = identity_entities
    if any(
        getattr(entity, "config_entry_id", None) not in {source_entry_id, new_entry_id}
        or getattr(entity, "config_subentry_id", None) is not None
        for entity in related
    ):
        raise RegistryRecoveryError(
            "entity_conflict", "Recovery entities have an unexpected owner"
        )

    # Foreign rows owned by either config entry must not be silently absorbed.
    related_ids = {str(entity.id) for entity in related}
    if any(
        getattr(entity, "config_entry_id", None) in {source_entry_id, new_entry_id}
        and str(getattr(entity, "id", "")) not in related_ids
        for entity in all_entities
    ):
        raise RegistryRecoveryError(
            "entity_conflict", "Config entry owns entities outside the recovery group"
        )

    anchors = [
        entity
        for entity in related
        if getattr(entity, "domain", None) == "climate"
        and getattr(entity, "unique_id", None)
        == f"{registry_identity}_virtual_thermostat"
    ]
    if len(anchors) != 1:
        raise RegistryRecoveryError(
            "ambiguous_group", "Recovery climate anchor is missing or ambiguous"
        )
    if (
        _fingerprint(source_entry_id, registry_identity, device_id, related)
        != fingerprint
    ):
        raise RegistryRecoveryError(
            "stale_group", "Recovery group changed while the flow was open"
        )

    # Verify the registry's own unique-ID index before mutating ownership.
    for entity in related:
        indexed = entity_registry.async_get_entity_id(
            entity.domain, DOMAIN, entity.unique_id
        )
        if indexed != entity.entity_id:
            raise RegistryRecoveryError(
                "entity_conflict", "Recovery unique-ID index is inconsistent"
            )

    source_entities = [
        entity
        for entity in related
        if getattr(entity, "config_entry_id", None) == source_entry_id
    ]
    already_adopted = not source_entities

    try:
        if new_entry_id not in owners:
            kwargs: dict[str, Any] = {"add_config_entry_id": new_entry_id}
            if getattr(device, "primary_config_entry", None) == source_entry_id:
                kwargs["device_info_type"] = "primary"
            device_registry.async_update_device(device_id, **kwargs)

        for entity in source_entities:
            disabled_by = getattr(entity, "disabled_by", None)
            entity_registry.async_update_entity(
                entity.entity_id,
                config_entry_id=new_entry_id,
                disabled_by=(
                    None if _enum_value(disabled_by) == "config_entry" else disabled_by
                ),
            )

        # Explicitly clear the derived config-entry state for a resumed
        # adoption; user, integration, device and Home Assistant choices remain.
        for entity in related:
            refreshed = entity_registry.async_get(entity.entity_id)
            if (
                refreshed is not None
                and _enum_value(getattr(refreshed, "disabled_by", None))
                == "config_entry"
            ):
                entity_registry.async_update_entity(entity.entity_id, disabled_by=None)

        refreshed_device = device_registry.async_get(device_id)
        if refreshed_device is not None:
            finish: dict[str, Any] = {}
            if source_entry_id in _device_owners(refreshed_device):
                finish["remove_config_entry_id"] = source_entry_id
            if (
                _enum_value(getattr(refreshed_device, "disabled_by", None))
                == "config_entry"
            ):
                finish["disabled_by"] = None
            if finish:
                device_registry.async_update_device(device_id, **finish)
    except Exception as err:
        # Public HA APIs cannot reassign an entity to a missing config entry.
        # Leave the safe forward-resumable state in place and retry on setup.
        raise RegistryRecoveryError(
            "stale_group", "Registry adoption was interrupted and can be resumed"
        ) from err

    return RegistryRecoveryResult(
        entity_count=len(related),
        device_count=1,
        already_adopted=already_adopted,
    )


def verify_recovered_registry_group(
    entity_registry: Any,
    device_registry: Any,
    *,
    new_entry_id: str,
    registry_identity: str,
    device_id: str,
    expected_entity_count: int,
) -> RegistryRecoveryResult:
    """Verify native resurrection/adoption before clearing recovery markers."""
    device = device_registry.async_get(device_id)
    if device is None:
        raise RegistryRecoveryError("stale_group", "Recovered device was not restored")
    if _domain_identities(device) != {registry_identity}:
        raise RegistryRecoveryError(
            "device_conflict", "Recovered device identity changed"
        )
    if _device_owners(device) != {new_entry_id}:
        raise RegistryRecoveryError(
            "device_conflict", "Recovered device has an unexpected owner"
        )
    identity_device = device_registry.async_get_device(
        identifiers={(DOMAIN, registry_identity)}
    )
    if identity_device is None or identity_device.id != device_id:
        raise RegistryRecoveryError(
            "device_conflict", "Recovered identity resolves to another device"
        )

    all_entities = _registry_entities(entity_registry)
    related = [
        entity
        for entity in all_entities
        if getattr(entity, "platform", None) == DOMAIN
        and _entity_suffix(entity, registry_identity) is not None
    ]
    if len(related) < expected_entity_count or any(
        getattr(entity, "config_entry_id", None) != new_entry_id
        or getattr(entity, "config_subentry_id", None) is not None
        or getattr(entity, "device_id", None) != device_id
        for entity in related
    ):
        raise RegistryRecoveryError(
            "entity_conflict", "Recovered entity group is incomplete or conflicted"
        )
    anchors = [
        entity
        for entity in related
        if getattr(entity, "domain", None) == "climate"
        and getattr(entity, "unique_id", None)
        == f"{registry_identity}_virtual_thermostat"
    ]
    if len(anchors) != 1:
        raise RegistryRecoveryError(
            "ambiguous_group", "Recovered climate anchor is missing or ambiguous"
        )
    if any(
        getattr(entity, "config_entry_id", None) == new_entry_id
        and entity not in related
        for entity in all_entities
    ):
        raise RegistryRecoveryError(
            "entity_conflict", "Recovered entry owns unrelated registry entities"
        )
    return RegistryRecoveryResult(
        entity_count=len(related),
        device_count=1,
        already_adopted=True,
    )


__all__ = [
    "OrphanedRegistryGroup",
    "RegistryRecoveryError",
    "RegistryRecoveryResult",
    "adopt_orphaned_registry_group",
    "find_orphaned_registry_groups",
    "verify_recovered_registry_group",
]
