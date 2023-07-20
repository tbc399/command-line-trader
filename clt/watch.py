from typing import List

import click

from clt.context import Context, WatchlistItem


@click.group()
def watch():
    pass


@watch.command()
@click.argument("name")
@click.option("--notes", "-n", default="")
@click.pass_context
def add(ctx, name: str, notes: str):

    context: Context = ctx.obj["context"]
    watchlist: List[WatchlistItem] = context.watchlist

    if name not in watchlist:
        watchlist.append(WatchlistItem(name=name.upper(), notes=notes))
    else:
        click.echo(f"{name.upper()} is already being watched")


@watch.command()
@click.argument("name")
@click.pass_context
def remove(ctx, name: str):

    context: Context = ctx.obj["context"]
    watchlist: List[WatchlistItem] = context.watchlist

    to_be_removed = None

    for x in watchlist:
        if x.name.lower() == name.lower():
            to_be_removed = x

    if to_be_removed is not None:
        watchlist.remove(to_be_removed)


@watch.command()
@click.pass_context
def clear(ctx):

    context: Context = ctx.obj["context"]
    watchlist: List[WatchlistItem] = context.watchlist
    watchlist.clear()


@watch.command(name="list")
@click.pass_context
def list_(ctx):

    watchlist: List[WatchlistItem] = ctx.obj["context"].watchlist

    for item in watchlist:
        click.echo(f"{item.name}: {item.notes}")
