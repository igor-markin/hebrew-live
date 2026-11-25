"""Which MLX wheel is installed and which Metal device it runs on, and how much memory MLX may keep."""
import importlib.metadata

REQUIRED_WHEEL_PLATFORM = 'macosx_26_0'  # Neural-accelerator build; 14_0/15_0 wheels run without it.
DISTRIBUTIONS = ('mlx', 'mlx-metal')
# MLX keeps freed buffers for reuse, by default up to its whole memory limit. Live translation frees
# buffers of a new size on every call, so without a limit of its own they pile up until macOS swaps.
CACHE_LIMIT_BYTES = 256 * 1024 * 1024


def limit_cache(mx):
    """Return freed buffers above the limit to the system; memory in use is not limited."""
    mx.set_cache_limit(CACHE_LIMIT_BYTES)
    return CACHE_LIMIT_BYTES


def wheel_tags(names=DISTRIBUTIONS):
    """Tags from each distribution's WHEEL file; None when the metadata is not shipped."""
    result = {}
    for name in names:
        try:
            text = importlib.metadata.distribution(name).read_text('WHEEL')
        except importlib.metadata.PackageNotFoundError:
            text = None
        result[name] = [line.split(':', 1)[1].strip() for line in text.splitlines()
                        if line.startswith('Tag:')] if text else None
    return result


def accelerator_wheel(tags):
    """True/False when every distribution reports a tag, None when unknown."""
    if not tags or any(not value for value in tags.values()):
        return None
    return all(any(REQUIRED_WHEEL_PLATFORM in tag for tag in value) for value in tags.values())


def device_info(mx):
    try:
        return {key: value for key, value in mx.device_info().items()
                if key in ('device_name', 'architecture', 'memory_size', 'max_recommended_working_set_size')}
    except Exception:
        return {}


def describe(mx):
    tags = wheel_tags()
    return dict(wheel_tags=tags, neural_accelerator_wheel=accelerator_wheel(tags), **device_info(mx))
