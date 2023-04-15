import asyncio
import itertools
import sys
from functools import wraps


def asink(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


async def load_and_spin(coroutine, info: str, persist: bool = True):
    task = asyncio.ensure_future(coroutine)

    spinner = itertools.cycle(["|", "/", "-", "\\"])

    while not task.done():
        sys.stdout.write("\r")
        sys.stdout.write(f"{info} {cyan(next(spinner))} ")
        sys.stdout.flush()
        await asyncio.sleep(0.1)

    if persist:
        sys.stdout.write("\r")
        sys.stdout.write(f"{info}  \n")
    else:
        sys.stdout.write("\r")
        sys.stdout.write(" " * len(f"{info} {cyan(next(spinner))} "))
        sys.stdout.write("\r")

    return task.result()


def red(text):
    return f"\033[91m{text}\033[0m"


def green(text):
    return f"\033[32m{text}\033[0m"


def cyan(text):
    return f"\033[36m{text}\033[0m"


def percent_change(start, end):
    return ((end - start) / start) * 100


def color_pl(pl):
    return green(pl) if pl >= 0 else red(pl)
