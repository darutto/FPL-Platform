"""Secret-safe typed failures at the canonical distribution boundary."""


class DistributionError(RuntimeError):
    reason_code = "distribution_error"


class DistributionConfigError(DistributionError):
    reason_code = "invalid_configuration"


class RemoteStoreError(DistributionError):
    reason_code = "remote_unavailable"


class ImmutableConflictError(DistributionError):
    reason_code = "immutable_conflict"


class PointerRaceError(DistributionError):
    reason_code = "pointer_race"


class ArtifactSizeError(DistributionError):
    reason_code = "artifact_oversize"


class RemoteValidationError(DistributionError):
    reason_code = "remote_validation_failed"


class SyncLockError(DistributionError):
    reason_code = "sync_lock_timeout"
