"""Which MLX wheel is installed and which Metal device it runs on (diagnostics only)."""
import importlib.metadata

REQUIRED_WHEEL_PLATFORM = 'macosx_26_0'  # Neural-accelerator build; 14_0/15_0 wheels run without it.
DISTRIBUTIONS = ('mlx', 'mlx-metal')


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
