"""Validated per-fragment timing, independent of model weights."""
import math
DEFAULTS=(1.5,1.,0,4.,.6)
FIELDS=('first_seconds','interval_seconds','preview_limit','fragment_seconds','silence_seconds')
def validate(values):
    if not isinstance(values,dict) or set(values)!=set(FIELDS):raise ValueError('Нужны все пять настроек')
    result=[]
    for key in FIELDS:
        value=values[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (value<0 if key=='preview_limit' else value<=0):raise ValueError('Недопустимое значение: '+key)
        if key=='preview_limit' and value!=int(value):raise ValueError('Число блоков должно быть целым')
        result.append(value)
    return tuple(result)
def as_dict(values):return dict(zip(FIELDS,values))
